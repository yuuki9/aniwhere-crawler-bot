"""AniList 인기 애니를 MySQL `works`에 동기화.

실행 예 (프로젝트 루트에서):
  python scripts/sync_anilist_works.py
  python scripts/sync_anilist_works.py --max-pages 5 --per-page 50

환경변수: DB_* , TMDB_API_KEY (.env)
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


async def _run(max_pages: int, per_page: int) -> int:
    from app.services.anilist_works_sync_service import sync_popular_anime_to_works

    stats = await sync_popular_anime_to_works(max_pages=max_pages, per_page=per_page)
    print(
        f"OK pages={stats.pages_fetched} media={stats.media_processed} "
        f"upserts_ok={stats.works_upserted}",
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="AniList → works 테이블 동기화")
    p.add_argument("--max-pages", type=int, default=20, help="최대 Page 순회 수 (기본 20)")
    p.add_argument("--per-page", type=int, default=50, help="페이지당 미디어 수 1~50 (기본 50)")
    args = p.parse_args()
    try:
        return asyncio.run(_run(args.max_pages, args.per_page))
    except KeyboardInterrupt:
        print("중단됨", file=sys.stderr)
        return 130
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
