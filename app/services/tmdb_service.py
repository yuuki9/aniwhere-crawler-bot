"""TMDB v3: 영문 검색 후 한국어(ko-KR) 표제 보강 (https://developer.themoviedb.org/reference/search-tv)"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"


def tmdb_search_query_from_titles(title: dict[str, Any]) -> str:
    """
    `english` 우선(`Attack on Titan Season 2` 등 시즌 표기 포함 그대로), 없으면 `romaji`.
    작품당 TMDB 검색 호출은 search 한 번(+상세 한 번)으로 유지된다.
    """
    if not isinstance(title, dict):
        title = {}
    english = (title.get("english") or "").strip()
    romaji = (title.get("romaji") or "").strip()
    return english if english else romaji


async def lookup_korean_tv_title(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    search_query: str,
    first_air_date_year: int | None = None,
) -> str | None:
    """영문(또는 라틴) 검색어로 TV를 찾은 뒤, `GET /tv/{id}` `language=ko-KR` 의 `name` 반환."""
    q = (search_query or "").strip()
    if not api_key or not q:
        return None

    search_params: dict[str, Any] = {
        "api_key": api_key,
        "query": q,
        "language": "en-US",
    }
    if first_air_date_year is not None:
        search_params["first_air_date_year"] = first_air_date_year

    try:
        r = await client.get(f"{TMDB_API_BASE}/search/tv", params=search_params)
        if r.status_code == 401:
            logger.warning("[tmdb] 인증 실패(401) — TMDB_API_KEY 확인")
            return None
        if r.status_code != 200:
            logger.warning("[tmdb] search/tv 실패 status=%s body=%s", r.status_code, r.text[:200])
            return None
        payload = r.json()
        results = payload.get("results") or []
        if not results:
            return None
        tv_id = results[0].get("id")
        if not isinstance(tv_id, int):
            return None

        r2 = await client.get(
            f"{TMDB_API_BASE}/tv/{tv_id}",
            params={"api_key": api_key, "language": "ko-KR"},
        )
        if r2.status_code != 200:
            logger.debug("[tmdb] tv/%s ko-KR 실패 status=%s", tv_id, r2.status_code)
            return None
        detail = r2.json()
        name = detail.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except httpx.HTTPError:
        logger.exception("[tmdb] HTTP 오류")
        return None
    return None


async def attach_korean_titles(
    api_key: str | None,
    media_items: list[dict[str, Any]],
    *,
    max_concurrent: int = 6,
) -> list[dict[str, Any]]:
    """각 항목에 `koreanTitle` 키를 붙임. TMDB 키 없거나 쿼리 없으면 None."""
    if not api_key:
        return [{**m, "koreanTitle": None} for m in media_items]

    sem = asyncio.Semaphore(max_concurrent)

    async def enrich_one(client: httpx.AsyncClient, item: dict[str, Any]) -> dict[str, Any]:
        title = item.get("title") or {}
        if not isinstance(title, dict):
            title = {}
        q = tmdb_search_query_from_titles(title).strip()
        if not q:
            return {**item, "koreanTitle": None}

        year = item.get("seasonYear")
        first_year = int(year) if isinstance(year, int) else None

        async with sem:
            ko = await lookup_korean_tv_title(
                client,
                api_key=api_key,
                search_query=q,
                first_air_date_year=first_year,
            )
        return {**item, "koreanTitle": ko}

    async with httpx.AsyncClient(timeout=20.0) as client:
        out = await asyncio.gather(*[enrich_one(client, m) for m in media_items])
    return list(out)
