"""네이버 블로그 검색 API로 상점별 블로그 URL을 수집하는 서비스."""

import asyncio
import json
import logging
import urllib.parse
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.schemas.shop import ShopRecord

logger = logging.getLogger(__name__)


async def search_blog_urls(client: httpx.AsyncClient, shop_name: str) -> list[str]:
    """단일 상점명으로 네이버 블로그 검색 후 URL 리스트 반환. 429 시 백오프 재시도."""
    settings = get_settings()
    params = {
        "query": shop_name,
        "display": settings.naver_blog_results_per_shop,
        "sort": "date",
    }
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }
    max_attempts = 8
    for attempt in range(max_attempts):
        try:
            resp = await client.get(
                "https://openapi.naver.com/v1/search/blog.json",
                params=params,
                headers=headers,
            )
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                if ra and ra.isdigit():
                    wait = float(ra)
                else:
                    wait = min(2.0**attempt, 60.0) + 0.5
                logger.warning(
                    "[naver] 429 Too Many Requests | shop=%r | 대기=%.1fs (%s/%s)",
                    shop_name,
                    wait,
                    attempt + 1,
                    max_attempts,
                )
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [item["link"] for item in items]
        except Exception as e:
            logger.warning("네이버 블로그 검색 실패 (shop=%s): %s", shop_name, e)
            return []
    logger.warning("[naver] 재시도 소진 (shop=%r)", shop_name)
    return []


async def collect_blog_urls(records: list[ShopRecord]) -> list[dict]:
    """
    ShopRecord 리스트를 받아 각 상점의 블로그 URL을 수집하고
    blog 필드가 채워진 딕셔너리 리스트를 반환한다.
    """
    settings = get_settings()
    logger.info(
        "[naver] 단계=blog_search_start | 상점수=%s | display=%s",
        len(records),
        settings.naver_blog_results_per_shop,
    )
    # 동시 요청 시 네이버 429 빈발 → 상점별 순차 + 요청 간 짧은 간격
    pace_sec = 0.35
    results: list[list[str]] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, r in enumerate(records):
            urls = await search_blog_urls(client, r.name)
            results.append(urls)
            if i + 1 < len(records):
                await asyncio.sleep(pace_sec)

    rows = [
        {
            "address": r.address,
            "name": r.name,
            "px": r.px,
            "py": r.py,
            "blog": ",".join(urls),
        }
        for r, urls in zip(records, results)
    ]
    total_urls = sum(len(u) for u in results)
    zero_url_shops = sum(1 for u in results if len(u) == 0)
    logger.info(
        "[naver] 단계=blog_search_end | 수집_URL_총개수=%s | URL없는_상점=%s/%s",
        total_urls,
        zero_url_shops,
        len(records),
    )
    return rows


def save_blog_csv(rows: list[dict], output_path: str) -> Path:
    """수집 결과를 CSV 파일로 저장하고 경로를 반환한다."""
    import csv

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["address", "name", "px", "py", "blog"])
        writer.writeheader()
        writer.writerows(rows)

    logger.info("블로그 URL CSV 저장 완료: %s (%d개 상점)", path, len(rows))
    return path
