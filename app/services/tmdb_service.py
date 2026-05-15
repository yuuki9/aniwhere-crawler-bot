"""TMDB v3: 영문 검색 후 표제(ko 우선)·로고 URL 보강 (https://developer.themoviedb.org/reference/search-tv)"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
_TMDB_LOGO_SIZE = "w500"


def _non_empty_title_field(detail: dict[str, Any]) -> str | None:
    """TMDB tv 상세에서 `name` 우선, 비었으면 `original_name`."""
    for key in ("name", "original_name"):
        v = detail.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def tmdb_search_query_from_titles(title: dict[str, Any]) -> str:
    """
    `english` 우선, 없으면 `romaji`. — `search/tv`는 이 문자열로 한 번만 호출.
    """
    if not isinstance(title, dict):
        title = {}
    english = (title.get("english") or "").strip()
    romaji = (title.get("romaji") or "").strip()
    return english if english else romaji


def _tmdb_logo_url_from_logos(logos: list[Any]) -> str | None:
    """`GET /tv/{id}/images` 의 logos 배열에서 우선순위(ko → 무언어 → en → 기타)로 하나를 고른 절대 URL."""
    if not isinstance(logos, list) or not logos:
        return None

    def _lang_rank(logo: dict[str, Any]) -> int:
        lang = logo.get("iso_639_1")
        if lang == "ko":
            return 0
        if lang is None or lang == "":
            return 1
        if lang == "en":
            return 2
        return 3

    dict_logos = [L for L in logos if isinstance(L, dict) and L.get("file_path")]
    if not dict_logos:
        return None
    best = min(
        dict_logos,
        key=lambda L: (
            _lang_rank(L),
            -float(L.get("vote_average") or 0),
            -int(L.get("width") or 0),
        ),
    )
    fp = best.get("file_path")
    if not isinstance(fp, str) or not fp.strip():
        return None
    return f"{TMDB_IMAGE_BASE}/{_TMDB_LOGO_SIZE}{fp}"


async def lookup_korean_tv_title(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    search_query: str,
    first_air_date_year: int | None = None,
) -> str | None:
    """호환용: 표제만 필요할 때 `lookup_tmdb_tv_metadata` 의 첫 반환값."""
    title, _logo = await lookup_tmdb_tv_metadata(
        client,
        api_key=api_key,
        search_query=search_query,
        first_air_date_year=first_air_date_year,
    )
    return title


async def _tv_detail_title_fallback(
    client: httpx.AsyncClient,
    *,
    tv_id: int,
    api_key: str,
    language: str,
) -> str | None:
    """추가 언어로 상세 1회 조회 후 표제 보간."""
    r = await client.get(
        f"{TMDB_API_BASE}/tv/{tv_id}",
        params={"api_key": api_key, "language": language},
    )
    if r.status_code != 200:
        logger.debug("[tmdb] tv/%s %s 실패 status=%s", tv_id, language, r.status_code)
        return None
    return _non_empty_title_field(r.json())


async def lookup_tmdb_tv_metadata(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    search_query: str,
    first_air_date_year: int | None = None,
) -> tuple[str | None, str | None]:
    """
    `search/tv` 로 TV id 확보 후,
    상세는 ko-KR → (비면) original_name 동일 응답 → en-US → ja-JP 순으로 표제 보간.
    로고는 images 1회. 모두 비면 (None, 로고 또는 None).
    """
    q = (search_query or "").strip()
    if not api_key or not q:
        return None, None

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
            return None, None
        if r.status_code != 200:
            logger.warning("[tmdb] search/tv 실패 status=%s body=%s", r.status_code, r.text[:200])
            return None, None
        payload = r.json()
        results = payload.get("results") or []
        if not results:
            return None, None
        tv_id = results[0].get("id")
        if not isinstance(tv_id, int):
            return None, None

        detail_coro = client.get(
            f"{TMDB_API_BASE}/tv/{tv_id}",
            params={"api_key": api_key, "language": "ko-KR"},
        )
        images_coro = client.get(
            f"{TMDB_API_BASE}/tv/{tv_id}/images",
            params={
                "api_key": api_key,
                "include_image_language": "ko,en,null",
            },
        )
        r_detail, r_img = await asyncio.gather(detail_coro, images_coro)

        resolved_title: str | None = None
        if r_detail.status_code == 200:
            detail = r_detail.json()
            resolved_title = _non_empty_title_field(detail)
        else:
            logger.debug("[tmdb] tv/%s ko-KR 실패 status=%s", tv_id, r_detail.status_code)

        if not resolved_title:
            resolved_title = await _tv_detail_title_fallback(
                client, tv_id=tv_id, api_key=api_key, language="en-US"
            )
        if not resolved_title:
            resolved_title = await _tv_detail_title_fallback(
                client, tv_id=tv_id, api_key=api_key, language="ja-JP"
            )

        logo_url: str | None = None
        if r_img.status_code == 200:
            img_payload = r_img.json()
            logos = img_payload.get("logos") or []
            logo_url = _tmdb_logo_url_from_logos(logos)
        else:
            logger.debug("[tmdb] tv/%s/images 실패 status=%s", tv_id, r_img.status_code)

        return resolved_title, logo_url
    except httpx.HTTPError:
        logger.exception("[tmdb] HTTP 오류")
        return None, None


async def attach_korean_titles(
    api_key: str | None,
    media_items: list[dict[str, Any]],
    *,
    max_concurrent: int = 6,
) -> list[dict[str, Any]]:
    """각 항목에 `koreanTitle`, `tmdbLogoUrl` 키를 붙임. TMDB 키 없거나 쿼리 없으면 둘 다 None.

    반환 리스트 길이는 항상 `media_items` 와 동일(개별 보강 실패 시 해당 항목만 None).
    """
    if not api_key:
        return [{**m, "koreanTitle": None, "tmdbLogoUrl": None} for m in media_items]

    sem = asyncio.Semaphore(max_concurrent)

    async def enrich_one(client: httpx.AsyncClient, item: dict[str, Any]) -> dict[str, Any]:
        title = item.get("title") or {}
        if not isinstance(title, dict):
            title = {}
        q = tmdb_search_query_from_titles(title).strip()
        if not q:
            return {**item, "koreanTitle": None, "tmdbLogoUrl": None}

        year = item.get("seasonYear")
        first_year = int(year) if isinstance(year, int) else None

        async with sem:
            ko, logo_url = await lookup_tmdb_tv_metadata(
                client,
                api_key=api_key,
                search_query=q,
                first_air_date_year=first_year,
            )
        return {**item, "koreanTitle": ko, "tmdbLogoUrl": logo_url}

    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await asyncio.gather(
            *[enrich_one(client, m) for m in media_items],
            return_exceptions=True,
        )
    out: list[dict[str, Any]] = []
    for i, res in enumerate(results):
        item = media_items[i]
        if isinstance(res, BaseException):
            logger.warning("[tmdb] TMDB 보강 실패 idx=%s: %s", i, res)
            out.append({**item, "koreanTitle": None, "tmdbLogoUrl": None})
        else:
            out.append(res)
    return out
