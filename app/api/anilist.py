"""AniList GraphQL 프록시 (https://docs.anilist.co/guide/introduction)"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.schemas.anilist import (
    AnilistMediaDetailResponse,
    TrendingAnimePageResponse,
    WorksCatalogSyncResponse,
)
from app.services.anilist_graphql import (
    MEDIA_BY_ID_QUERY,
    TRENDING_ANIME_QUERY,
    AnilistGraphQLError,
    exclude_english_season_titles,
    post_anilist_graphql,
)
from app.services.anilist_works_sync_service import sync_popular_anime_to_works
from app.services.tmdb_service import attach_korean_titles

router = APIRouter(prefix="/api/v1/anilist", tags=["AniList"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


def require_works_sync_key(
    x_works_sync_key: Annotated[str | None, Header(alias="X-Works-Sync-Key")] = None,
) -> None:
    """환경변수 WORKS_SYNC_API_KEY 와 일치해야 함."""
    expected = (get_settings().works_sync_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="WORKS_SYNC_API_KEY 미설정 — 동기화 API 비활성화",
        )
    got = (x_works_sync_key or "").strip()
    if got != expected:
        raise HTTPException(status_code=401, detail="동기화 키가 올바르지 않습니다")


async def _anilist_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        return await post_anilist_graphql(query, variables)
    except AnilistGraphQLError as e:
        raise HTTPException(502, str(e)) from e


@router.get(
    "/trending-anime",
    response_model=TrendingAnimePageResponse,
    summary="인기순 애니 목록 (AniList)",
    description=(
        "AniList GraphQL `Page.media(sort: POPULARITY_DESC, type: ANIME)` 결과를 반환합니다. "
        "`popularity` 내림차순으로 정렬됩니다(Tie-break id). "
        "`title.english`에 `Season`이 포함된 항목(분리 시즌 엔트리 등)은 결과에서 제외합니다. "
        "`TMDB_API_KEY`가 있으면 [TMDB](https://api.themoviedb.org/3/tv)에서 한글 표제(`koreanTitle`)와 "
        "로고 이미지 URL(`tmdbLogoUrl`)을 붙입니다. "
        "[AniList API 소개](https://docs.anilist.co/guide/introduction)"
    ),
)
@limiter.limit("30/minute")
async def trending_anime(
    request: Request,
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(
        50,
        ge=1,
        le=50,
        alias="perPage",
        description="페이지당 항목 수 (AniList 상한 고려 최대 50)",
    ),
):
    data = await _anilist_graphql(
        TRENDING_ANIME_QUERY,
        {"page": page, "perPage": per_page},
    )
    page_payload = data.get("Page") or {}
    media_raw: list = page_payload.get("media") or []
    media_raw = exclude_english_season_titles([m for m in media_raw if isinstance(m, dict)])
    settings = get_settings()
    key = (settings.tmdb_api_key or "").strip() or None
    media_out = await attach_korean_titles(key, media_raw)
    if len(media_out) != len(media_raw):
        logger.warning(
            "[api] attach_korean_titles 길이 불일치 (%s != %s), TMDB 보강 필드 폴백",
            len(media_out),
            len(media_raw),
        )
        media_out = [{**m, "koreanTitle": None, "tmdbLogoUrl": None} for m in media_raw]
    media_out.sort(
        key=lambda m: (
            -max(0, int((m.get("popularity") or 0))),
            -int((m.get("id") or 0)),
        )
    )
    logger.info(
        "[api] GET /api/v1/anilist/trending-anime | page=%s perPage=%s media_count=%s tmdb=%s",
        page,
        per_page,
        len(media_out),
        bool(key),
    )
    return TrendingAnimePageResponse(
        pageInfo=page_payload.get("pageInfo"),
        media=media_out,
    )


@router.get(
    "/media/{media_id}",
    response_model=AnilistMediaDetailResponse,
    summary="Media 단건 (제목 등)",
    description=(
        "`Media(id)` — `title.romaji/english/native`, `seasonYear`. "
        "`TMDB_API_KEY`가 있으면 TMDB에서 한글 표제(`koreanTitle`)와 로고 URL(`tmdbLogoUrl`)을 붙입니다. "
        "[AniList GraphQL](https://docs.anilist.co/guide/graphql/)"
    ),
)
@limiter.limit("60/minute")
async def media_by_id(
    request: Request,
    media_id: int = Path(..., ge=1, description="AniList Media id (예: 15125 Teekyuu)"),
):
    data = await _anilist_graphql(MEDIA_BY_ID_QUERY, {"id": media_id})
    raw = data.get("Media")
    if raw is None:
        raise HTTPException(404, f"Media id={media_id} 를 찾을 수 없습니다")

    settings = get_settings()
    key = (settings.tmdb_api_key or "").strip() or None
    base = raw if isinstance(raw, dict) else {}
    enriched = await attach_korean_titles(key, [base])
    r0 = enriched[0] if enriched else {**base, "koreanTitle": None, "tmdbLogoUrl": None}

    logger.info(
        "[api] GET /api/v1/anilist/media/%s | tmdb=%s",
        media_id,
        bool(key),
    )
    return AnilistMediaDetailResponse(
        id=int(r0["id"]),
        title=r0.get("title"),
        koreanTitle=r0.get("koreanTitle"),
        tmdbLogoUrl=r0.get("tmdbLogoUrl"),
    )


@router.post(
    "/sync-works",
    response_model=WorksCatalogSyncResponse,
    summary="works 카탈로그 동기화 (AniList 인기 애니)",
    description=(
        "AniList 인기순 애니 페이지를 순회해 MySQL `works`에 upsert합니다. "
        "헤더 `X-Works-Sync-Key`에 환경변수 `WORKS_SYNC_API_KEY`와 동일한 값이 필요합니다."
    ),
)
@limiter.limit("12/hour")
async def sync_works_catalog(
    request: Request,
    _: Annotated[None, Depends(require_works_sync_key)],
    max_pages: int = Query(
        20,
        ge=1,
        le=100,
        alias="maxPages",
        description="최대 Page 순회 수",
    ),
    per_page: int = Query(
        50,
        ge=1,
        le=50,
        alias="perPage",
        description="페이지당 미디어 수 (AniList 상한 50)",
    ),
):
    client_host = getattr(request.client, "host", None)
    logger.info(
        "[api] POST /api/v1/anilist/sync-works | maxPages=%s perPage=%s client=%s",
        max_pages,
        per_page,
        client_host,
    )
    stats = await sync_popular_anime_to_works(max_pages=max_pages, per_page=per_page)
    return WorksCatalogSyncResponse(
        pagesFetched=stats.pages_fetched,
        mediaProcessed=stats.media_processed,
        worksUpserted=stats.works_upserted,
    )
