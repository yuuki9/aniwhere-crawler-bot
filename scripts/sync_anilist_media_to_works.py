"""단일 AniList Media → TMDB 보강 → MySQL `works` upsert.

예:
  python scripts/sync_anilist_media_to_works.py --media-id 21519

환경변수: DB_* , TMDB (설정 기본값 사용 가능)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

MEDIA_FOR_WORKS_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    id
    title {
      romaji
      english
      native
    }
    type
    format
    seasonYear
    startDate {
      year
    }
    genres
    popularity
    coverImage {
      extraLarge
      large
    }
  }
}
"""


async def _run(media_id: int) -> int:
    from app.core.config import get_settings
    from app.services.anilist_graphql import AnilistGraphQLError, post_anilist_graphql
    from app.services.db_service import get_db_pool, upsert_work_anilist_catalog
    from app.services.tmdb_service import attach_korean_titles

    settings = get_settings()
    key = (settings.tmdb_api_key or "").strip() or None

    try:
        data = await post_anilist_graphql(MEDIA_FOR_WORKS_QUERY, {"id": media_id})
    except AnilistGraphQLError as e:
        print("FAIL AniList:", e, file=sys.stderr)
        return 1

    raw = data.get("Media")
    if raw is None or not isinstance(raw, dict):
        print(f"FAIL Media id={media_id} 없음", file=sys.stderr)
        return 1

    enriched_list = await attach_korean_titles(key, [raw])
    m = enriched_list[0] if enriched_list else raw

    pool = await get_db_pool()
    try:
        wid = await upsert_work_anilist_catalog(pool, m)
    finally:
        pool.close()
        await pool.wait_closed()

    print(
        "OK",
        f"work_id={wid}",
        f"anilist_id={m.get('id')}",
        f"koreanTitle={m.get('koreanTitle')!r}",
        f"tmdbLogoUrl={'set' if m.get('tmdbLogoUrl') else None}",
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="AniList Media 1건을 works에 반영")
    p.add_argument(
        "--media-id",
        type=int,
        default=21519,
        help="AniList Media id (너의 이름은. 기본 21519)",
    )
    args = p.parse_args()
    try:
        return asyncio.run(_run(args.media_id))
    except KeyboardInterrupt:
        print("중단됨", file=sys.stderr)
        return 130
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
