from pydantic import BaseModel
from typing import Optional


class ShopSummary(BaseModel):
    """Gemini가 반환하는 단일 상점 요약 결과."""

    name: str
    address: str
    summary: str
    error: Optional[str] = None


class SummarizeBatchResponse(BaseModel):
    """배치 요약 API 응답."""

    total: int
    succeeded: int
    failed: int
    results: list[ShopSummary]
