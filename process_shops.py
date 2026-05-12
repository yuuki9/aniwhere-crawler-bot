"""레거시 배치: regions / shop_details 등 구 DB 스키마 전제.

신규 DB가 init_db.sql 과 같다면 run_pipeline.py 사용을 권장한다.

- 중복 방지 (이름으로 체크)
- 15초 간격
- 실패 시 2회 재시도 (30초 대기)
"""

import asyncio
import csv
from pathlib import Path
from app.services.db_service import get_db_pool
from app.services.blog_crawl_service import crawl_blog_context
from app.services.refine_service import refine_shop
from app.schemas.shop import ShopRecord


async def get_or_create_region(cur, name):
    if not name:
        return None
    await cur.execute("SELECT id FROM regions WHERE name = %s", (name,))
    row = await cur.fetchone()
    return row[0] if row else (await cur.execute("INSERT INTO regions (name) VALUES (%s)", (name,)) or cur.lastrowid)


async def get_or_create_category(cur, name):
    await cur.execute("SELECT id FROM categories WHERE name = %s", (name,))
    row = await cur.fetchone()
    return row[0] if row else (await cur.execute("INSERT INTO categories (name) VALUES (%s)", (name,)) or cur.lastrowid)


async def get_or_create_work(cur, name):
    await cur.execute("SELECT id FROM works WHERE name = %s", (name,))
    row = await cur.fetchone()
    return row[0] if row else (await cur.execute("INSERT INTO works (name) VALUES (%s)", (name,)) or cur.lastrowid)


async def is_already_saved(cur, name):
    await cur.execute("SELECT id FROM shops WHERE name = %s", (name,))
    return await cur.fetchone() is not None


async def process_one(pool, shop, idx, total):
    print(f"\n[{idx}/{total}] {shop.name}")

    # 중복 체크
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if await is_already_saved(cur, shop.name):
                print(f"   ⏭️  이미 저장됨, 스킵")
                return True

    # 크롤링
    print(f"   크롤링 중... ({len(shop.blog)}개 블로그)")
    crawl_text = await crawl_blog_context(shop.blog[:5])
    print(f"   크롤링: {len(crawl_text)}자 / ~{len(crawl_text)//4} 토큰")

    if not crawl_text:
        print(f"   ⚠️  크롤링 실패")
        return False

    # Gemini 요약
    print(f"   Gemini 요약 중... (입력 {len(crawl_text)}자)")
    result = await refine_shop(shop, crawl_text)

    if result.get("error"):
        print(f"   ⚠️  요약 실패: {result['error']}")
        return False

    rdb = result.get("rdb")
    if rdb is None:
        print(f"   ⏭️  가챠/피규어샵 아님 → DB 저장 생략")
        return True

    kb_text = result.get("knowledge_base_text") or ""
    print(f"   categories={rdb.get('categories')}")
    print(f"   works={rdb.get('works')}")
    print(f"   [벡터DB] {kb_text}")

    # MySQL 저장
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

            for c in rdb.get("categories", []):
                cid = await get_or_create_category(cur, c)
                await cur.execute("INSERT IGNORE INTO shop_categories (shop_id, category_id) VALUES (%s, %s)", (shop_id, cid))

            for w in rdb.get("works", []):
                wid = await get_or_create_work(cur, w)
                await cur.execute("INSERT IGNORE INTO shop_works (shop_id, work_id) VALUES (%s, %s)", (shop_id, wid))

            for link in rdb.get("links", []):
                lt = link.get("type", "")
                if lt in ("blog", "insta", "x", "place", "homepage"):
                    await cur.execute("INSERT INTO shop_links (shop_id, type, url) VALUES (%s, %s, %s)",
                                      (shop_id, lt, link["url"]))

    print(f"   ✅ 완료 (shop_id: {shop_id})")
    return True


async def main():
    print("=" * 80)
    print("전체 상점 처리 (중복 방지 + 15초 간격 + 재시도)")
    print("=" * 80)

    pool = await get_db_pool()

    with open(Path("data/shop_with_blogs.csv"), encoding="utf-8-sig") as f:
        shops = [ShopRecord(**row) for row in csv.DictReader(f)]
    print(f"   {len(shops)}개 상점 로드\n")

    failed = []
    success = 0

    # 1차 시도 (15초 간격)
    for i, shop in enumerate(shops, 1):
        ok = await process_one(pool, shop, i, len(shops))
        if ok:
            success += 1
        else:
            failed.append((i, shop))
        await asyncio.sleep(15)

    # 재시도 (최대 2회, 30초 간격)
    for retry in range(1, 3):
        if not failed:
            break
        print(f"\n{'=' * 80}")
        print(f"재시도 {retry}/2: {len(failed)}개 (30초 간격)")
        print("=" * 80)

        still_failed = []
        for idx, shop in failed:
            ok = await process_one(pool, shop, idx, len(shops))
            if ok:
                success += 1
            else:
                still_failed.append((idx, shop))
            await asyncio.sleep(30)
        failed = still_failed

    pool.close()
    await pool.wait_closed()

    if failed:
        print(f"\n⚠️  최종 실패:")
        for _, s in failed:
            print(f"   - {s.name}")

    print(f"\n{'=' * 80}")
    print(f"완료: 성공 {success}개 / 실패 {len(failed)}개 / 전체 {len(shops)}개")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
