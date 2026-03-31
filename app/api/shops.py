"""하비숍 CSV 업로드 및 요약 엔드포인트."""

import logging
from fastapi import APIRouter, UploadFile, File, Query
from fastapi.responses import JSONResponse

from app.schemas.summary import SummarizeBatchResponse
from app.services.csv_service import parse_upload_to_records
from app.services.gemini_service import summarize_shops_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shops", tags=["shops"])


@router.post(
    "/summarize",
    response_model=SummarizeBatchResponse,
    summary="CSV 업로드 후 Gemini로 상점 요약",
    description=(
        "CSV 파일을 업로드하면 각 상점 정보를 파싱하고 "
        "Gemini API를 통해 상점 특징 요약문을 반환합니다."
    ),
)
async def summarize_shops_from_csv(
    file: UploadFile = File(..., description="갸차/피규어샵 정보가 담긴 CSV 파일"),
    concurrency: int = Query(default=5, ge=1, le=20, description="Gemini 동시 요청 수"),
):
    records = await parse_upload_to_records(file)
    summaries = await summarize_shops_batch(records, concurrency=concurrency)

    succeeded = [s for s in summaries if s.error is None]
    failed = [s for s in summaries if s.error is not None]

    return SummarizeBatchResponse(
        total=len(summaries),
        succeeded=len(succeeded),
        failed=len(failed),
        results=summaries,
    )


@router.post(
    "/parse",
    summary="CSV 파싱 결과만 반환 (요약 없음)",
    description="Gemini 호출 없이 CSV 파싱 및 전처리 결과만 확인하는 디버그용 엔드포인트.",
)
async def parse_csv_only(
    file: UploadFile = File(...),
):
    records = await parse_upload_to_records(file)
    return JSONResponse(
        content={
            "total": len(records),
            "records": [r.model_dump() for r in records],
        }
    )
