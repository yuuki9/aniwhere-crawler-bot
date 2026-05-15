"""TMDB v3: AniList title 로 search/movie 또는 search/tv 를 여러 번 시도 후 ko-KR 표제·로고 보강."""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
_TMDB_LOGO_SIZE = "w500"


def tmdb_release_year_hint(media: dict[str, Any]) -> int | None:
    """AniList `seasonYear` 또는 `startDate.year` (영화 등)."""
    y = media.get("seasonYear")
    if isinstance(y, int):
        return y
    sd = media.get("startDate")
    if isinstance(sd, dict):
        yy = sd.get("year")
        if isinstance(yy, int):
            return yy
    return None


def tmdb_search_queries_from_anilist_title(title: dict[str, Any]) -> list[str]:
    """
    AniList `title`에서 TMDB 검색어 순서 (중복 제거).

    `english` → `romaji` → `native` 순으로 각각 별도 검색 시도 (TV·영화 공통).
    """
    if not isinstance(title, dict):
        title = {}
    out: list[str] = []
    for key in ("english", "romaji", "native"):
        v = (title.get(key) or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def tmdb_search_query_from_titles(title: dict[str, Any]) -> str:
    """첫 번째 검색어 (english 우선, 없으면 romaji, …). 호환용."""
    qs = tmdb_search_queries_from_anilist_title(title)
    return qs[0] if qs else ""


def _tmdb_logo_url_from_logos(logos: list[Any]) -> str | None:
    """TV·영화 images 의 logos 배열에서 우선순위(ko → 무언어 → en → 기타)로 하나를 고른 절대 URL."""
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


async def lookup_tmdb_tv_metadata(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    search_query: str,
    first_air_date_year: int | None = None,
) -> tuple[str | None, str | None]:
    """
    단일 `search/tv` 쿼리 후 TV id로 `language=ko-KR` 상세의 **`name`만** 표제로 사용.
    (비면 표제 None — en/ja 보간 없음.) 로고는 images 1회.
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

        korean_name: str | None = None
        if r_detail.status_code == 200:
            detail = r_detail.json()
            name = detail.get("name")
            if isinstance(name, str) and name.strip():
                korean_name = name.strip()
        else:
            logger.debug("[tmdb] tv/%s ko-KR 실패 status=%s", tv_id, r_detail.status_code)

        logo_url: str | None = None
        if r_img.status_code == 200:
            img_payload = r_img.json()
            logos = img_payload.get("logos") or []
            logo_url = _tmdb_logo_url_from_logos(logos)
        else:
            logger.debug("[tmdb] tv/%s/images 실패 status=%s", tv_id, r_img.status_code)

        return korean_name, logo_url
    except httpx.HTTPError:
        logger.exception("[tmdb] HTTP 오류")
        return None, None


async def lookup_tmdb_movie_metadata(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    search_query: str,
    primary_release_year: int | None = None,
) -> tuple[str | None, str | None]:
    """
    단일 `search/movie` 후 `movie/{id}` 의 `language=ko-KR` 상세에서 **`title`만** 사용.
    로고는 `/movie/{id}/images`.
    """
    q = (search_query or "").strip()
    if not api_key or not q:
        return None, None

    search_params: dict[str, Any] = {
        "api_key": api_key,
        "query": q,
        "language": "en-US",
    }
    if primary_release_year is not None:
        search_params["primary_release_year"] = primary_release_year

    try:
        r = await client.get(f"{TMDB_API_BASE}/search/movie", params=search_params)
        if r.status_code == 401:
            logger.warning("[tmdb] 인증 실패(401) — TMDB_API_KEY 확인")
            return None, None
        if r.status_code != 200:
            logger.warning("[tmdb] search/movie 실패 status=%s body=%s", r.status_code, r.text[:200])
            return None, None
        payload = r.json()
        results = payload.get("results") or []
        if not results:
            return None, None
        movie_id = results[0].get("id")
        if not isinstance(movie_id, int):
            return None, None

        detail_coro = client.get(
            f"{TMDB_API_BASE}/movie/{movie_id}",
            params={"api_key": api_key, "language": "ko-KR"},
        )
        images_coro = client.get(
            f"{TMDB_API_BASE}/movie/{movie_id}/images",
            params={
                "api_key": api_key,
                "include_image_language": "ko,en,null",
            },
        )
        r_detail, r_img = await asyncio.gather(detail_coro, images_coro)

        korean_title: str | None = None
        if r_detail.status_code == 200:
            detail = r_detail.json()
            t = detail.get("title")
            if isinstance(t, str) and t.strip():
                korean_title = t.strip()
        else:
            logger.debug("[tmdb] movie/%s ko-KR 실패 status=%s", movie_id, r_detail.status_code)

        logo_url: str | None = None
        if r_img.status_code == 200:
            img_payload = r_img.json()
            logos = img_payload.get("logos") or []
            logo_url = _tmdb_logo_url_from_logos(logos)
        else:
            logger.debug("[tmdb] movie/%s/images 실패 status=%s", movie_id, r_img.status_code)

        return korean_title, logo_url
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
        queries = tmdb_search_queries_from_anilist_title(title)
        if not queries:
            return {**item, "koreanTitle": None, "tmdbLogoUrl": None}

        year_hint = tmdb_release_year_hint(item)
        fmt = (item.get("format") or "").strip().upper()

        best_ko: str | None = None
        best_logo: str | None = None

        async with sem:
            for idx, q in enumerate(queries):
                if fmt == "MOVIE":
                    ko, logo_url = await lookup_tmdb_movie_metadata(
                        client,
                        api_key=api_key,
                        search_query=q,
                        primary_release_year=year_hint,
                    )
                else:
                    ko, logo_url = await lookup_tmdb_tv_metadata(
                        client,
                        api_key=api_key,
                        search_query=q,
                        first_air_date_year=year_hint,
                    )
                if logo_url and best_logo is None:
                    best_logo = logo_url
                if ko:
                    best_ko = ko
                    best_logo = logo_url or best_logo
                    break
                if idx > 0:
                    logger.debug("[tmdb] 보조 검색어 시도 — 아직 ko-KR name 없음 | query=%r", q[:80])

        return {**item, "koreanTitle": best_ko, "tmdbLogoUrl": best_logo}

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
