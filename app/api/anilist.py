"""AniList GraphQL 프록시 (https://docs.anilist.co/guide/introduction)"""

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.schemas.anilist import AnilistMediaDetailResponse, TrendingAnimePageResponse
from app.services.tmdb_service import attach_korean_titles

router = APIRouter(prefix="/api/v1/anilist", tags=["AniList"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"

_ENGLISH_SEASON_WORD = re.compile(r"\bseason\b", re.IGNORECASE)


def _exclude_english_season_titles(media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`title.english`에 단어 Season(대소문자 무관)이 있으면 목록에서 제외 (예: Attack on Titan Season 2)."""
    out: list[dict[str, Any]] = []
    for m in media:
        if not isinstance(m, dict):
            continue
        title = m.get("title") or {}
        eng = (title.get("english") or "").strip() if isinstance(title, dict) else ""
        if eng and _ENGLISH_SEASON_WORD.search(eng):
            continue
        out.append(m)
    return out


TRENDING_ANIME_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      total
      hasNextPage
    }
    media(sort: POPULARITY_DESC, type: ANIME) {
      id
      idMal
      title {
        romaji
        english
        native
      }
      type
      format
      status
      season
      seasonYear
      episodes
      duration
      genres
      coverImage {
        extraLarge
        large
        color
      }
      bannerImage
      averageScore
      meanScore
      popularity
      trending
    }
  }
}
"""

MEDIA_BY_ID_QUERY = """
query ($id: Int) {
    Media(id: $id) {
    id
    title {
      romaji
      english
      native
    }
    seasonYear
  }
}
"""


async def _anilist_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = {"query": query, "variables": variables}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                ANILIST_GRAPHQL_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()
            body = r.json()
    except httpx.HTTPError as e:
        logger.exception("[api] AniList GraphQL 요청 실패")
        raise HTTPException(502, f"AniList 연결 오류: {e}") from e

    errs = body.get("errors")
    if errs:
        msg = errs[0].get("message", str(errs)) if isinstance(errs, list) else str(errs)
        logger.warning("[api] AniList GraphQL errors: %s", errs)
        raise HTTPException(502, f"AniList GraphQL 오류: {msg}")

    return body.get("data") or {}


@router.get(
    "/trending-anime",
    response_model=TrendingAnimePageResponse,
    summary="인기순 애니 목록 (AniList)",
    description=(
        "AniList GraphQL `Page.media(sort: POPULARITY_DESC, type: ANIME)` 결과를 반환합니다. "
        "`popularity` 내림차순으로 정렬됩니다(Tie-break id). "
        "`title.english`에 `Season`이 포함된 항목(분리 시즌 엔트리 등)은 결과에서 제외합니다. "
        "`TMDB_API_KEY`가 있으면 [TMDB](https://api.themoviedb.org/3/tv)에서 한글 표제를 `koreanTitle`에 붙입니다. "
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
    media_raw = _exclude_english_season_titles([m for m in media_raw if isinstance(m, dict)])
    settings = get_settings()
    key = (settings.tmdb_api_key or "").strip() or None
    media_out = await attach_korean_titles(key, media_raw)
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
        "`TMDB_API_KEY`가 있으면 TMDB에서 한글 표제를 `koreanTitle`에 붙입니다. "
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
    enriched = await attach_korean_titles(key, [raw])
    r0 = enriched[0]

    logger.info(
        "[api] GET /api/v1/anilist/media/%s | tmdb=%s",
        media_id,
        bool(key),
    )
    return AnilistMediaDetailResponse(
        id=int(r0["id"]),
        title=r0.get("title"),
        koreanTitle=r0.get("koreanTitle"),
    )
