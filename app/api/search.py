"""RAG 검색 API 엔드포인트"""

from fastapi import APIRouter, Query, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.services.rag_service import search_shops

router = APIRouter(prefix="/api/v1", tags=["RAG Search"])
limiter = Limiter(key_func=get_remote_address)

# 입력 가드레일: 차단 키워드
BLOCKED_KEYWORDS = [
    "정치", "대통령", "선거", "국회", "정당",
    "종교", "기독교", "불교", "이슬람", "교회",
    "성인", "야동", "포르노", "섹스",
]


def validate_query(query: str) -> None:
    """입력 쿼리 검증 (가드레일)"""
    q_lower = query.lower()
    
    # 1. 길이 검증
    if len(query.strip()) < 2:
        raise HTTPException(400, "검색어는 최소 2자 이상이어야 합니다")
    
    # 2. 차단 키워드 검증
    for keyword in BLOCKED_KEYWORDS:
        if keyword in q_lower:
            raise HTTPException(
                400, 
                "피규어/애니메이션 굿즈샵 관련 질문만 답변 가능합니다"
            )


@router.get("/search")
@limiter.limit("10/minute")  # Rate Limiting: 분당 10회
async def search_shops_endpoint(
    request: Request,
    q: str = Query(
        ..., 
        max_length=200,
        description="검색 쿼리 (예: 홍대 진격의 거인)"
    ),
    n: int = Query(
        default=3, 
        ge=1, 
        le=10, 
        description="반환할 상점 수"
    )
):
    """
    RAG 기반 상점 검색
    
    - **q**: 검색 쿼리 (예: "홍대 진격의 거인", "강남 포켓몬 굿즈")
    - **n**: 반환할 상점 수 (기본 3개, 최대 10개)
    - **Rate Limit**: 분당 10회
    
    Returns:
        - query: 입력 쿼리
        - shops: 유사한 상점 목록
        - answer: Gemini가 생성한 자연어 답변
    """
    # 입력 검증
    validate_query(q)
    
    # RAG 검색 실행
    try:
        result = await search_shops(q, n)
        return result
    except Exception as e:
        raise HTTPException(500, f"검색 중 오류가 발생했습니다: {str(e)}")
