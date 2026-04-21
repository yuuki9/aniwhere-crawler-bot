"""
data/shop.csv 기준 전체 파이프라인 (CLI)

1) 네이버 블로그 검색으로 blog URL 보강 → shop_with_blogs.csv
2) 블로그 크롤링 → Gemini refine
3) MySQL 저장 + ChromaDB 임베딩 upsert (+ 로컬 knowledge_base/*.txt)

실행 예:
  python run_pipeline.py
  python run_pipeline.py --no-collect --input data/shop_with_blogs.csv
  python run_pipeline.py --no-mysql --no-chroma
  python run_pipeline.py --update-existing   # DB·Chroma 재생성 시 기존 shop_id PK와 Chroma 문서 id(str) 유지
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.config import get_settings
from app.services.blog_crawl_service import crawl_blog_context
from app.services.chroma_ingest_service import upsert_shop_knowledge
from app.services.db_service import (
    get_db_pool,
    get_shop_id_by_name,
    save_shop_to_db,
    shop_exists_by_name,
    stop_mysql_ssh_tunnel,
    update_shop_in_db,
    upsert_shop_details,
)
from app.services.naver_search_service import collect_blog_urls, save_blog_csv
from app.services.refine_service import refine_shop, save_knowledge_base_doc
from app.utils.local_csv import load_shop_records_from_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

Outcome = Literal[
    "saved",
    "skip_duplicate",
    "skip_not_figure",
    "fail_crawl",
    "fail_refine",
    "fail_config",
]


@dataclass
class ShopPipelineResult:
    outcome: Outcome
    name: str
    shop_id: int | None = None
    detail: str = ""

    @property
    def is_hard_fail(self) -> bool:
        return self.outcome in ("fail_crawl", "fail_refine", "fail_config")


def _print_shop_line(idx: int, total: int, r: ShopPipelineResult) -> None:
    """Docker/터미널에서 한눈에 보이도록 표준 출력에 한 줄 요약."""
    sid = f"shop_id={r.shop_id}" if r.shop_id is not None else "shop_id=-"
    extra = f" | {r.detail}" if r.detail else ""
    print(f"[pipeline {idx}/{total}] {r.outcome:16} | {sid} | {r.name!r}{extra}", flush=True)


def _print_final_summary(rows: list[ShopPipelineResult]) -> None:
    c = Counter(r.outcome for r in rows)
    print("", flush=True)
    print("========== 파이프라인 요약 ==========", flush=True)
    print(
        f"전체 {len(rows)} | 저장 saved={c['saved']} | "
        f"건너뜀(중복)={c['skip_duplicate']} | 건너뜀(비가챠·비피규어)={c['skip_not_figure']} | "
        f"실패 크롤={c['fail_crawl']} | 실패 refine={c['fail_refine']} | "
        f"실패 설정={c['fail_config']}",
        flush=True,
    )
    print("--------------------------------------", flush=True)
    for i, r in enumerate(rows, 1):
        sid = str(r.shop_id) if r.shop_id is not None else "-"
        tail = f" {r.detail}" if r.detail else ""
        print(f"  {i:3}. [{r.outcome}] id={sid} {r.name!r}{tail}", flush=True)
    print("======================================", flush=True)


async def _process_one_shop(
    pool,
    shop,
    idx: int,
    total: int,
    *,
    do_mysql: bool,
    do_chroma: bool,
    update_existing: bool,
    max_blog_links: int,
    output_dir: str,
) -> ShopPipelineResult:
    name = shop.name
    logger.info("[pipeline %s/%s] 시작 | shop=%r", idx, total, name)

    if do_mysql and await shop_exists_by_name(pool, name) and not update_existing:
        logger.info("[pipeline %s/%s] 단계=skip_mysql_duplicate | shop=%r", idx, total, name)
        r = ShopPipelineResult("skip_duplicate", name, detail="이미 DB에 동일 상점명")
        _print_shop_line(idx, total, r)
        return r

    blogs = shop.blog[:max_blog_links] if shop.blog else []
    logger.info(
        "[pipeline %s/%s] 단계=crawl_start | shop=%r | blog_links=%s",
        idx,
        total,
        name,
        len(blogs),
    )
    crawl_text = await crawl_blog_context(blogs)
    if not crawl_text:
        logger.warning(
            "[pipeline %s/%s] 단계=crawl_end | shop=%r | 실패=빈_본문",
            idx,
            total,
            name,
        )
        r = ShopPipelineResult("fail_crawl", name, detail="블로그 본문 없음")
        _print_shop_line(idx, total, r)
        return r

    logger.info(
        "[pipeline %s/%s] 단계=crawl_end | shop=%r | 본문_자수=%s",
        idx,
        total,
        name,
        len(crawl_text),
    )
    logger.info(
        "[pipeline %s/%s] 단계=refine_start | shop=%r | 입력_자수=%s",
        idx,
        total,
        name,
        len(crawl_text),
    )
    result = await refine_shop(shop, crawl_text)
    if result.get("error"):
        err = str(result["error"])
        logger.warning(
            "[pipeline %s/%s] 단계=refine_end | shop=%r | 실패=%s",
            idx,
            total,
            name,
            err,
        )
        r = ShopPipelineResult("fail_refine", name, detail=err[:200])
        _print_shop_line(idx, total, r)
        return r

    rdb = result.get("rdb")
    if rdb is None:
        logger.info(
            "[pipeline %s/%s] 단계=refine_end | shop=%r | is_figure_relevant=False → 저장_생략",
            idx,
            total,
            name,
        )
        r = ShopPipelineResult("skip_not_figure", name, detail="가챠/피규어샵 관련 아님")
        _print_shop_line(idx, total, r)
        return r

    kb = (result.get("knowledge_base_text") or "").strip()

    if kb:
        kb_path = save_knowledge_base_doc(name, kb, output_dir)
        logger.info(
            "[pipeline %s/%s] 단계=kb_txt | shop=%r | path=%s | 자수=%s",
            idx,
            total,
            name,
            kb_path,
            len(kb),
        )
    else:
        logger.info("[pipeline %s/%s] 단계=kb_txt | shop=%r | 생략(빈_KB)", idx, total, name)

    shop_id: int | None = None
    persist_mysql_kind = ""
    if do_mysql:
        existing_sid = await get_shop_id_by_name(pool, name)
        if existing_sid is not None:
            persist_mysql_kind = "갱신"
            logger.info(
                "[pipeline %s/%s] 단계=mysql_update_start | shop=%r | shop_id=%s (기존 PK 유지)",
                idx,
                total,
                name,
                existing_sid,
            )
            await update_shop_in_db(pool, existing_sid, rdb)
            shop_id = existing_sid
        else:
            persist_mysql_kind = "신규"
            logger.info("[pipeline %s/%s] 단계=mysql_insert_start | shop=%r", idx, total, name)
            shop_id = await save_shop_to_db(pool, rdb)
        await upsert_shop_details(
            pool,
            shop_id,
            description=kb if kb else None,
            raw_crawl_text=crawl_text,
        )
        logger.info(
            "[pipeline %s/%s] 단계=mysql_persist_end | shop=%r | shop_id=%s",
            idx,
            total,
            name,
            shop_id,
        )
    elif do_chroma and kb:
        logger.error(
            "[pipeline %s/%s] 단계=mysql | shop=%r | 오류=MySQL_없이_Chroma_불가",
            idx,
            total,
            name,
        )
        r = ShopPipelineResult("fail_config", name, detail="MySQL 없이 Chroma 불가")
        _print_shop_line(idx, total, r)
        return r

    if do_chroma and shop_id is not None and kb:
        logger.info(
            "[pipeline %s/%s] 단계=chroma_upsert_start | shop_id=%s (문서 id 동일) | shop=%r",
            idx,
            total,
            shop_id,
            name,
        )
        upsert_shop_knowledge(shop_id, kb)
        logger.info(
            "[pipeline %s/%s] 단계=chroma_upsert_end | shop_id=%s | shop=%r",
            idx,
            total,
            shop_id,
            name,
        )
    elif do_chroma:
        logger.info(
            "[pipeline %s/%s] 단계=chroma | shop=%r | 생략 (shop_id=%s kb_non_empty=%s)",
            idx,
            total,
            name,
            shop_id,
            bool(kb),
        )

    logger.info("[pipeline %s/%s] 완료 | shop=%r", idx, total, name)
    kb_detail = f"KB {len(kb)}자"
    if persist_mysql_kind:
        kb_detail = f"{kb_detail} [{persist_mysql_kind}]"
    r = ShopPipelineResult("saved", name, shop_id=shop_id, detail=kb_detail)
    _print_shop_line(idx, total, r)
    return r


async def run_pipeline_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    root = Path(__file__).resolve().parent
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = root / input_path
    blogs_path = Path(args.blogs_out)
    if not blogs_path.is_absolute():
        blogs_path = root / blogs_path

    logger.info(
        "[pipeline] 시작 | collect=%s mysql=%s chroma=%s update_existing=%s input=%s blogs_out=%s "
        "max_blog_links=%s sleep_sec=%s limit=%s output_dir=%s",
        args.collect,
        args.mysql,
        args.chroma,
        args.update_existing,
        input_path,
        blogs_path,
        args.max_blog_links or settings.pipeline_max_blog_links_crawl,
        args.sleep if args.sleep is not None else settings.pipeline_sleep_sec,
        args.limit,
        settings.output_dir,
    )

    records = load_shop_records_from_csv(input_path)
    if not records:
        logger.error("[pipeline] 중단 | 이유=CSV_비어있음_또는_오류 | path=%s", input_path)
        return 1

    if args.collect:
        if not settings.naver_client_id or not settings.naver_client_secret:
            logger.error(
                "[pipeline] 중단 | 이유=네이버_API_키_없음 (.env NAVER_CLIENT_ID/SECRET)"
            )
            return 1
        logger.info(
            "[pipeline] 단계=naver_collect | 상점수=%s | 저장예정=%s",
            len(records),
            blogs_path,
        )
        rows = await collect_blog_urls(records)
        blogs_path.parent.mkdir(parents=True, exist_ok=True)
        save_blog_csv(rows, str(blogs_path))
        records = load_shop_records_from_csv(blogs_path)
        logger.info(
            "[pipeline] 단계=csv_reload_after_naver | path=%s | 상점수=%s",
            blogs_path,
            len(records),
        )
    else:
        if not input_path.exists():
            logger.error("[pipeline] 중단 | 이유=입력파일_없음 | path=%s", input_path)
            return 1
        logger.info(
            "[pipeline] 단계=csv_load | path=%s | 상점수=%s",
            input_path,
            len(records),
        )
        records = load_shop_records_from_csv(input_path)

    if not records:
        logger.error("[pipeline] 중단 | 이유=처리할_상점_없음")
        return 1

    if args.limit is not None:
        if args.limit < 1:
            logger.error("[pipeline] 중단 | --limit 은 1 이상이어야 합니다 (받은 값=%s)", args.limit)
            return 1
        records = records[: args.limit]
        logger.info(
            "[pipeline] 단계=limit | CSV_앞에서_%s건만_처리 | 실제_상점수=%s",
            args.limit,
            len(records),
        )

    logger.info("[pipeline] 단계=shop_loop | 총_상점=%s", len(records))

    pool = None
    if args.mysql:
        logger.info("[pipeline] 단계=mysql_pool | 연결_시도")
        pool = await get_db_pool()
        logger.info("[pipeline] 단계=mysql_pool | 연결_완료")

    max_links = args.max_blog_links or settings.pipeline_max_blog_links_crawl
    sleep_sec = args.sleep if args.sleep is not None else settings.pipeline_sleep_sec

    results: list[ShopPipelineResult] = []
    try:
        for i, shop in enumerate(records, 1):
            r = await _process_one_shop(
                pool,
                shop,
                i,
                len(records),
                do_mysql=args.mysql,
                do_chroma=args.chroma,
                update_existing=args.update_existing,
                max_blog_links=max_links,
                output_dir=settings.output_dir,
            )
            results.append(r)
            if i < len(records) and sleep_sec > 0:
                logger.info(
                    "[pipeline] 단계=rate_limit_sleep | 다음까지_대기=%ss (%s/%s)",
                    sleep_sec,
                    i,
                    len(records),
                )
                await asyncio.sleep(sleep_sec)
    finally:
        if pool is not None:
            logger.info("[pipeline] 단계=mysql_pool | 종료")
            pool.close()
            await pool.wait_closed()
        stop_mysql_ssh_tunnel()

    fail = sum(1 for r in results if r.is_hard_fail)
    soft_ok = len(results) - fail
    logger.info(
        "[pipeline] 종료 | 하드실패=%s 그외완료=%s 전체=%s",
        fail,
        soft_ok,
        len(records),
    )
    _print_final_summary(results)
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="CSV 상단부터 N개 상점만 처리 (디버그·부분 실행용)",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="DB에 이미 있는 상점명이면 스킵하지 않고 재크롤·재정제 후 같은 shop_id로 MySQL 갱신 + Chroma ids=str(shop_id) upsert",
    )
    args = parser.parse_args()
    args.collect = not args.no_collect
    args.mysql = not args.no_mysql
    args.chroma = not args.no_chroma
    # --update-existing은 MySQL 대상일 때만 의미 있음
    if args.update_existing and not args.mysql:
        logger.error("--update-existing 은 MySQL을 끄면 사용할 수 없습니다.")
        sys.exit(1)

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
