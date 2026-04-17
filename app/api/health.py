import logging

from fastapi import APIRouter
from app.core.config import get_settings
from app.services.rag_service import get_chroma_collection

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", summary="서버 상태 확인")
async def health_check():
    settings = get_settings()
    # ChromaDB 상태 확인
    try:
        collection = get_chroma_collection()
        shop_count = collection.count()
        chromadb_status = "ok"
        logger.debug("[api] GET /health | chromadb=ok | shop_count=%s", shop_count)
    except Exception as e:
        chromadb_status = f"error: {str(e)}"
        shop_count = 0
        logger.warning("[api] GET /health | chromadb 실패: %s", e)

    return {
        "status": "ok",
        "env": settings.app_env,
        "chromadb": {
            "status": chromadb_status,
            "shop_count": shop_count
        }
    }
