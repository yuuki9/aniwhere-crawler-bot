"""
data/shop.csv 기준 전체 파이프라인 (CLI)

1) 네이버 블로그 검색으로 blog URL 보강 → shop_with_blogs.csv
2) 블로그 크롤링 → Gemini refine
3) MySQL 저장 + ChromaDB 임베딩 upsert (+ 로컬 knowledge_base/*.txt)

실행 예:
  python run_pipeline.py
  python run_pipeline.py --no-collect --input data/shop_with_blogs.csv
  python run_pipeline.py --no-mysql --no-chroma
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.services.blog_crawl_service import crawl_blog_context
from app.services.chroma_ingest_service import upsert_shop_knowledge
from app.services.db_service import get_db_pool, save_shop_to_db, shop_exists_by_name
from app.services.naver_search_service import collect_blog_urls, save_blog_csv
from app.services.refine_service import refine_shop, save_knowledge_base_doc
from app.utils.local_csv import load_shop_records_from_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _process_one_shop(
    pool,
    shop,
    idx: int,
    total: int,
    *,
    do_mysql: bool,
    do_chroma: bool,
    max_blog_links: int,
    output_dir: str,
) -> bool:
    name = shop.name
    logger.info("[%s/%s] %s", idx, total, name)

    if do_mysql and await shop_exists_by_name(pool, name):
        logger.info("  이미 MySQL에 존재 → 스킵")
        return True

    blogs = shop.blog[:max_blog_links] if shop.blog else []
    logger.info("  크롤링 (%s개 링크)", len(blogs))
    crawl_text = await crawl_blog_context(blogs)
    if not crawl_text:
        logger.warning("  크롤 실패 또는 빈 본문")
        return False

    logger.info("  Gemini refine (입력 %s자)", len(crawl_text))
    result = await refine_shop(shop, crawl_text)
    if result.get("error"):
        logger.warning("  refine 실패: %s", result["error"])
        return False

    rdb = result["rdb"]
    kb = (result.get("knowledge_base_text") or "").strip()

    if kb:
        save_knowledge_base_doc(name, kb, output_dir)

    shop_id: int | None = None
    if do_mysql:
        shop_id = await save_shop_to_db(pool, rdb)
        logger.info("  MySQL 저장 shop_id=%s", shop_id)
    elif do_chroma and kb:
        logger.error("  Chroma만 켜져 있고 MySQL이 꺼져 있으면 shop_id가 없습니다. --no-mysql 사용 시 --no-chroma 권장")
        return False

    if do_chroma and shop_id is not None and kb:
        upsert_shop_knowledge(shop_id, kb)
        logger.info("  Chroma upsert 완료 (shop_id=%s)", shop_id)

    return True


async def run_pipeline_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    root = Path(__file__).resolve().parent
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = root / input_path
    blogs_path = Path(args.blogs_out)
    if not blogs_path.is_absolute():
        blogs_path = root / blogs_path

    records = load_shop_records_from_csv(input_path)
    if not records:
        logger.error("상점 CSV가 비었거나 읽을 수 없습니다: %s", input_path)
        return 1

    if args.collect:
        if not settings.naver_client_id or not settings.naver_client_secret:
            logger.error(
                "네이버 API 키가 없습니다 (.env에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET). "
                "또는 --no-collect 로 이미 blog가 채워진 CSV를 지정하세요."
            )
            return 1
        logger.info("네이버 블로그 URL 수집 → %s", blogs_path)
        rows = await collect_blog_urls(records)
        blogs_path.parent.mkdir(parents=True, exist_ok=True)
        save_blog_csv(rows, str(blogs_path))
        records = load_shop_records_from_csv(blogs_path)
    else:
        if not input_path.exists():
            logger.error("입력 파일 없음: %s", input_path)
            return 1
        records = load_shop_records_from_csv(input_path)

    if not records:
        logger.error("처리할 상점이 없습니다.")
        return 1

    pool = None
    if args.mysql:
        pool = await get_db_pool()

    max_links = args.max_blog_links or settings.pipeline_max_blog_links_crawl
    sleep_sec = args.sleep if args.sleep is not None else settings.pipeline_sleep_sec

    ok, fail = 0, 0
    try:
        for i, shop in enumerate(records, 1):
            success = await _process_one_shop(
                pool,
                shop,
                i,
                len(records),
                do_mysql=args.mysql,
                do_chroma=args.chroma,
                max_blog_links=max_links,
                output_dir=settings.output_dir,
            )
            if success:
                ok += 1
            else:
                fail += 1
            if i < len(records) and sleep_sec > 0:
                await asyncio.sleep(sleep_sec)
    finally:
        if pool is not None:
            pool.close()
            await pool.wait_closed()

    logger.info("완료: 성공 %s / 실패 %s / 전체 %s", ok, fail, len(records))
    return 0 if fail == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="상점 CSV → 블로그 수집 → 크롤 → refine → MySQL + Chroma")
    parser.add_argument(
        "--input",
        default=None,
        help="CSV 경로. --no-collect 시 기본 data/shop_with_blogs.csv, 아니면 data/shop.csv",
    )
    parser.add_argument(
        "--blogs-out",
        default="data/shop_with_blogs.csv",
        help="블로그 URL 보강 결과 CSV (기본: data/shop_with_blogs.csv)",
    )
    parser.add_argument(
        "--no-collect",
        action="store_true",
        help="네이버 수집 생략 (--input 은 blog 컬럼이 있는 CSV, 예: shop_with_blogs.csv)",
    )
    parser.add_argument(
        "--no-mysql",
        action="store_true",
        help="MySQL 저장 생략",
    )
    parser.add_argument(
        "--no-chroma",
        action="store_true",
        help="ChromaDB upsert 생략",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="상점 간 대기(초). 미지정 시 설정 pipeline_sleep_sec",
    )
    parser.add_argument(
        "--max-blog-links",
        type=int,
        default=None,
        help="크롤에 사용할 블로그 링크 상한. 미지정 시 pipeline_max_blog_links_crawl",
    )
    args = parser.parse_args()
    args.collect = not args.no_collect
    args.mysql = not args.no_mysql
    args.chroma = not args.no_chroma

    if args.input is None:
        args.input = "data/shop_with_blogs.csv" if args.no_collect else "data/shop.csv"

    if args.mysql and not args.chroma:
        pass
    if not args.mysql and args.chroma:
        logger.error("MySQL 없이 Chroma만 켤 수 없습니다 (shop_id 필요). --no-chroma 를 추가하세요.")
        sys.exit(1)

    rc = asyncio.run(run_pipeline_async(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
