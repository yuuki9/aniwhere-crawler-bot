"""RAG 검색 API 엔드포인트"""

import logging

from fastapi import APIRouter, Query, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.query_guardrails import validate_query
from app.services.rag_service import search_shops

router = APIRouter(prefix="/api/v1", tags=["RAG Search"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


@router.get("/search")
@limiter.limit("10/minute")  # Rate Limiting: 분당 10회
async def search_shops_endpoint(
    request: Request,
    q: str = Query(
        ...,
        max_length=99,
        description="검색 쿼리 (99자 미만, 예: 홍대 진격의 거인)",
    ),
):
    """
    RAG 기반 상점 검색
    
    - **q**: 검색 쿼리 (예: "홍대 진격의 거인", "강남 포켓몬 굿즈")
    - **상점 목록**: ChromaDB에 있는 문서를 유사도 순으로 전부 조회하며, 환경변수 `RAG_CHROMA_MAX_DISTANCE`가 있으면 그 이내만 포함
    - **Rate Limit**: 분당 10회
    
    Returns:
        - query: 입력 쿼리
        - chroma_used: ChromaDB 컨텍스트를 썼는지 여부 (false면 Gemini 단독)
        - shops: chroma_used가 true일 때만 유사 상점 목록 (false면 빈 배열)
        - answer: Gemini가 생성한 자연어 답변 (캐릭터·애니 중심, 배송 안내 제외)
    """
    # 입력 검증
    validate_query(q)
    logger.info("[api] GET /api/v1/search | q_len=%s", len(q))

    # RAG 검색 실행
    try:
        result = await search_shops(q)
        logger.info(
            "[api] GET /api/v1/search | 완료 | shops_returned=%s answer_len=%s",
            len(result.get("shops") or []),
            len((result.get("answer") or "")),
        )
        return result
    except Exception as e:
        logger.exception("[api] GET /api/v1/search | 실패")
        raise HTTPException(500, f"검색 중 오류가 발생했습니다: {str(e)}")
