"""AniList 인기 애니 목록을 fetch하여 MySQL `works` 카탈로그에 반영."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.anilist_graphql import (
    TRENDING_ANIME_QUERY,
    AnilistGraphQLError,
    exclude_english_season_titles,
    post_anilist_graphql,
)
from app.services.db_service import get_db_pool, upsert_work_anilist_catalog
from app.services.tmdb_service import attach_korean_titles

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnilistWorksSyncStats:
    pages_fetched: int
    media_processed: int
    works_upserted: int


async def sync_popular_anime_to_works(
    *,
    max_pages: int = 20,
    per_page: int = 50,
    tmdb_api_key: str | None = None,
) -> AnilistWorksSyncStats:
    """
    AniList `Page.media(sort: POPULARITY_DESC, type: ANIME)` 페이지를 순회하며 `works` upsert.
    `max_pages`는 안전 상한; `hasNextPage`가 False면 조기 종료.
    """
    if per_page < 1 or per_page > 50:
        raise ValueError("per_page는 1~50 (AniList 상한)")
    if max_pages < 1:
        raise ValueError("max_pages >= 1")

    pool = await get_db_pool()
    key = (tmdb_api_key if tmdb_api_key is not None else get_settings().tmdb_api_key or "").strip() or None

    pages_fetched = 0
    media_processed = 0
    works_upserted = 0

    try:
        page = 1
        while page <= max_pages:
            try:
                data = await post_anilist_graphql(
                    TRENDING_ANIME_QUERY,
                    {"page": page, "perPage": per_page},
                )
            except AnilistGraphQLError:
                logger.exception("[sync] AniList 페이지 %s 실패", page)
                raise

            page_payload = data.get("Page") or {}
            media_raw = [m for m in (page_payload.get("media") or []) if isinstance(m, dict)]
            media_raw = exclude_english_season_titles(media_raw)
            enriched = await attach_korean_titles(key, media_raw)
            if len(enriched) != len(media_raw):
                logger.warning(
                    "[sync] attach_korean_titles 길이 불일치 → TMDB 필드 폴백",
                )
                enriched = [{**m, "koreanTitle": None, "tmdbLogoUrl": None} for m in media_raw]

            pages_fetched += 1

            for m in enriched:
                media_processed += 1
                try:
                    await upsert_work_anilist_catalog(pool, m)
                    works_upserted += 1
                except Exception:
                    logger.exception("[sync] works upsert 실패 media_id=%s", m.get("id"))

            pinfo = page_payload.get("pageInfo") or {}
            has_next = pinfo.get("hasNextPage") if isinstance(pinfo, dict) else None
            if not has_next:
                break
            page += 1

        logger.info(
            "[sync] 완료 pages=%s media=%s upserts_ok=%s",
            pages_fetched,
            media_processed,
            works_upserted,
        )
        return AnilistWorksSyncStats(
            pages_fetched=pages_fetched,
            media_processed=media_processed,
            works_upserted=works_upserted,
        )
    finally:
        pool.close()
        await pool.wait_closed()
