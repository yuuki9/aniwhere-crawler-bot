"""가챠/피규어샵 CSV 업로드 및 데이터 수집 엔드포인트."""

import json
import logging
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, UploadFile, File, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import get_settings
from app.services.blog_crawl_service import crawl_blog_details, crawl_blog_context
from app.services.csv_service import parse_upload_to_records
from app.services.naver_search_service import collect_blog_urls, save_blog_csv
from app.services.refine_service import refine_shop, save_knowledge_base_doc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shops", tags=["shops"])


@router.post(
    "/parse",
    summary="CSV 파싱 결과만 반환 (디버그용)",
    description="CSV 파싱 및 전처리 결과만 확인하는 디버그용 엔드포인트.",
)
async def parse_csv_only(
    file: UploadFile = File(...),
):
    logger.info("[api] POST /shops/parse | 시작")
    records = await parse_upload_to_records(file)
    logger.info("[api] POST /shops/parse | 완료 | records=%s", len(records))
    return JSONResponse(
        content={
            "total": len(records),
            "records": [r.model_dump() for r in records],
        }
    )


@router.post(
    "/crawl-export",
    summary="CSV의 blog 링크 크롤링 결과 파일 다운로드",
    description=(
        "CSV를 업로드하면 상점별 blog 링크를 크롤링하고, "
        "수집 결과를 JSON 파일로 내려줍니다."
    ),
)
async def crawl_export_from_csv(
    file: UploadFile = File(..., description="가챠/피규어샵 정보가 담긴 CSV 파일"),
):
    logger.info("[api] POST /shops/crawl-export | 시작")
    records = await parse_upload_to_records(file)
    logger.info("[api] POST /shops/crawl-export | 상점 루프 | count=%s", len(records))

    export_rows = []
    for record in records:
        logger.info("[api] crawl-export | 상점=%r | blog_링크수=%s", record.name, len(record.blog or []))
        crawled = await crawl_blog_details(record.blog)
        export_rows.append(
            {
                "name": record.name,
                "address": record.address,
                "blog_links": record.blog,
                "crawled_results": crawled,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_shops": len(export_rows),
        "results": export_rows,
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"crawl_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    logger.info(
        "[api] POST /shops/crawl-export | 완료 | shops=%s | file=%s",
        len(export_rows),
        filename,
    )
    return StreamingResponse(
        BytesIO(raw),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/collect-blog-urls",
    summary="CSV 상점 목록으로 네이버 블로그 URL 수집 후 파일 저장",
    description=(
        "CSV를 업로드하면 각 상점명으로 네이버 블로그 검색 API를 호출해 "
        "블로그 URL을 수집하고, output_path에 지정한 경로에 CSV 파일로 저장합니다."
    ),
)
async def collect_blog_urls_from_csv(
    file: UploadFile = File(..., description="상점 목록 CSV (address, name, px, py)"),
    output_path: str = Query(
        default=None,
        description="저장할 파일 경로. 미입력 시 OUTPUT_DIR/shop_with_blogs.csv 사용",
    ),
):
    settings = get_settings()
    logger.info("[api] POST /shops/collect-blog-urls | 시작 | output_path=%s", output_path)
    records = await parse_upload_to_records(file)
    rows = await collect_blog_urls(records)

    save_path = output_path or f"{settings.output_dir}/shop_with_blogs.csv"
    saved = save_blog_csv(rows, save_path)
    logger.info(
        "[api] POST /shops/collect-blog-urls | 완료 | rows=%s | saved=%s",
        len(rows),
        saved,
    )

    return JSONResponse(
        content={
            "total": len(rows),
            "saved_path": str(saved),
            "results": rows,
        }
    )


@router.post("/refine", summary="크롤링 원문 → Gemini 정제 (RDB JSON + KB 텍스트)")
async def refine_from_csv(
    file: UploadFile = File(...),
):
    settings = get_settings()
    logger.info("[api] POST /shops/refine | 시작")
    records = await parse_upload_to_records(file)
    results = []

    for i, record in enumerate(records, 1):
        logger.info(
            "[api] refine | %s/%s | 상점=%r | blog_링크수=%s",
            i,
            len(records),
            record.name,
            len(record.blog or []),
        )
        crawl_text = await crawl_blog_context(record.blog)
        refined = await refine_shop(record, crawl_text)

        kb = refined.get("knowledge_base_text")
        if kb and str(kb).strip() and not refined["error"]:
            save_knowledge_base_doc(record.name, str(kb).strip(), settings.output_dir)

        results.append({"name": record.name, **refined})

    logger.info("[api] POST /shops/refine | 완료 | total=%s", len(results))
    return JSONResponse(content={"total": len(results), "results": results})
