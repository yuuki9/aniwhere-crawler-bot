import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, shops
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("서버 시작 | env=%s", settings.app_env)
    yield
    logger.info("서버 종료")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Aniwhere AI — 피규어샵 데이터 수집 파이프라인",
        description="상점 CSV를 업로드하면 네이버 블로그 검색 및 크롤링으로 Knowledge Base용 데이터를 구축합니다.",
        version="0.2.0",
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(shops.router, prefix="/api/v1")

    return app


app = create_app()
