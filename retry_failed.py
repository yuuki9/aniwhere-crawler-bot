"""실패한 상점만 재시도 (10초 간격)"""

import asyncio
import csv
from pathlib import Path
from app.services.db_service import get_db_pool
from app.services.blog_crawl_service import crawl_blog_context
from app.services.refine_service import refine_shop
from app.schemas.shop import ShopRecord

FAILED_NAMES = [
    "쿄우마가챠샵 LC타워점", "유미상점", "라신반 서울본점", "키라키라토모 홍대하우스",
    "냐냐랜드", "지지코믹마켓 홍대점", "피규어센터 2호점", "호카상점",
    "레인몰", "아이돌룩", "스페이스 우라라 홍대입구점", "애니세카이 홍대점",
    "더쿠 연트럴파크점", "오모차랜드 홍대2호점", "CIH SHOP 케이북스", "헬로수미코",
    "푸숍", "쿠쿠 스페이스", "피규어프레소 홍대점", "피규어센터 1호점",
    "호에마켓 홍대점", "원피규어", "더쿠 홍대입구점", "피규어프렌즈",
    "아이노모노", "브라더굿즈 홍대", "최애굿즈 홍대점",
]


async def get_or_create_region(cur, region_name):
    if not region_name:
        return None
    await cur.execute("SELECT id FROM regions WHERE name = %s", (region_name,))
    row = await cur.fetchone()
    if row:
        return row[0]
    await cur.execute("INSERT INTO regions (name) VALUES (%s)", (region_name,))
    return cur.lastrowid


async def get_or_create_category(cur, name):
    await cur.execute("SELECT id FROM categories WHERE name = %s", (name,))
    row = await cur.fetchone()
    if row:
        return row[0]
    await cur.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
    return cur.lastrowid


async def get_or_create_work(cur, name):
    await cur.execute("SELECT id FROM works WHERE name = %s", (name,))
    row = await cur.fetchone()
    if row:
        return row[0]
    await cur.execute("INSERT INTO works (name) VALUES (%s)", (name,))
    return cur.lastrowid


async def main():
    print("=" * 80)
    print(f"실패 상점 재시도: {len(FAILED_NAMES)}개 (10초 간격)")
    print("=" * 80)

    pool = await get_db_pool()

    csv_path = Path("data/shop_with_blogs.csv")
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_shops = [ShopRecord(**row) for row in reader]

    shops = [s for s in all_shops if s.name in FAILED_NAMES]
    print(f"   대상: {len(shops)}개\n")

    success = 0
    still_failed = []

    for i, shop in enumerate(shops, 1):
        print(f"\n[{i}/{len(shops)}] {shop.name}")

        print(f"   크롤링 중... ({len(shop.blog)}개 블로그)")
        crawl_text = await crawl_blog_context(shop.blog[:5])
        print(f"   크롤링 결과: {len(crawl_text)}자 / 약 {len(crawl_text)//4} 토큰")

        if not crawl_text:
            print(f"   ⚠️  크롤링 실패")
            still_failed.append(shop.name)
            await asyncio.sleep(10)
            continue

        print(f"   Gemini 요약 중... (입력 {len(crawl_text)}자 / 약 {len(crawl_text)//4} 토큰)")
        result = await refine_shop(shop, crawl_text)

        if result.get("error"):
            print(f"   ⚠️  요약 실패: {result['error']}")
            still_failed.append(shop.name)
            await asyncio.sleep(10)
            continue

        rdb = result["rdb"]
        kb_text = result.get("knowledge_base_text", "")
        print(f"   Gemini 응답: categories={rdb.get('categories')}, works={rdb.get('works')}")
        print(f"   [벡터DB 저장 텍스트]")
        print(f"   {kb_text}")
        print(f"   ---")

        print(f"   MySQL 저장 중...")
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                region_id = await get_or_create_region(cur, rdb.get("region"))
                await cur.execute("""
                    INSERT INTO shops (name, address, px, py, floor, region_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (rdb["name"], rdb["address"], rdb["px"], rdb["py"],
                      rdb.get("floor"), region_id, rdb.get("status", "unverified")))
                shop_id = cur.lastrowid

                await cur.execute("""
                    INSERT INTO shop_details (shop_id, description, raw_crawl_text, crawled_at)
                    VALUES (%s, %s, %s, NOW())
                """, (shop_id, kb_text, crawl_text[:10000]))

                for cat_name in rdb.get("categories", []):
                    cat_id = await get_or_create_category(cur, cat_name)
                    await cur.execute("INSERT IGNORE INTO shop_categories (shop_id, category_id) VALUES (%s, %s)", (shop_id, cat_id))

                for work_name in rdb.get("works", []):
                    work_id = await get_or_create_work(cur, work_name)
                    await cur.execute("INSERT IGNORE INTO shop_works (shop_id, work_id) VALUES (%s, %s)", (shop_id, work_id))

                for link in rdb.get("links", []):
                    await cur.execute("INSERT INTO shop_links (shop_id, type, url) VALUES (%s, %s, %s)", (shop_id, link["type"], link["url"]))

        print(f"   ✅ 완료 (shop_id: {shop_id})")
        success += 1
        await asyncio.sleep(10)

    pool.close()
    await pool.wait_closed()

    if still_failed:
        print(f"\n⚠️  최종 실패: {still_failed}")

    print(f"\n{'=' * 80}")
    print(f"완료: 성공 {success}개 / 실패 {len(still_failed)}개 / 전체 {len(shops)}개")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
