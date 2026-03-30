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
    logger.info("서버 시작 | env=%s | model=%s", settings.app_env, settings.gemini_model)
    yield
    logger.info("서버 종료")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Aniwhere AI — 하비숍 요약 API",
        description="CSV로 업로드된 하비숍 데이터를 Gemini API로 요약합니다.",
        version="0.1.0",
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
