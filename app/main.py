import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.api import health, search, shops
from app.core.config import get_settings
from app.services.db_service import stop_mysql_ssh_tunnel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Rate Limiter 초기화
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("서버 시작 | env=%s", settings.app_env)
    yield
    stop_mysql_ssh_tunnel()
    logger.info("서버 종료")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Aniwhere AI — 피규어샵 검색 API",
        description="피규어/애니메이션 굿즈샵 RAG 검색 서비스",
        version="1.0.0",
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    # Rate Limiter 등록
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(shops.router)

    return app


app = create_app()
