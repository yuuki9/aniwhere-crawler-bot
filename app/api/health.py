from fastapi import APIRouter
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="서버 상태 확인")
async def health_check():
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.app_env,
    }
