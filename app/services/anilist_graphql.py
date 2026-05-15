"""AniList GraphQL 클라이언트 (API·동기화 공통). https://docs.anilist.co/guide/graphql/"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"

_ENGLISH_SEASON_WORD = re.compile(r"\bseason\b", re.IGNORECASE)


class AnilistGraphQLError(Exception):
    """HTTP 오류 또는 GraphQL errors 필드."""


def exclude_english_season_titles(media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`title.english`에 단어 Season이 있으면 목록에서 제외."""
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


async def post_anilist_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """GraphQL `data` 루트 dict 반환. 실패 시 AnilistGraphQLError."""
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
        logger.exception("[anilist] GraphQL HTTP 실패")
        raise AnilistGraphQLError(f"AniList 연결 오류: {e}") from e

    errs = body.get("errors")
    if errs:
        if isinstance(errs, list) and errs:
            err0 = errs[0]
            msg = (
                err0.get("message", str(errs))
                if isinstance(err0, dict)
                else str(err0)
            )
        else:
            msg = str(errs)
        logger.warning("[anilist] GraphQL errors: %s", errs)
        raise AnilistGraphQLError(f"AniList GraphQL 오류: {msg}")

    return body.get("data") or {}
