"""블로그 URL에서 요약용 텍스트를 추출하는 크롤링 서비스."""

import asyncio
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


def _clean_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _extract_page_text(html: str, max_chars: int) -> str:
    """HTML에서 요약에 유용한 텍스트를 우선순위로 추출한다."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates: list[str] = []

    # 메타 설명 우선
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        candidates.append(_clean_text(meta_desc["content"]))

    og_desc = soup.find("meta", attrs={"property": "og:description"})
    if og_desc and og_desc.get("content"):
        candidates.append(_clean_text(og_desc["content"]))

    # 본문 텍스트 후보
    article = soup.find("article")
    if article:
        candidates.append(_clean_text(article.get_text(" ", strip=True)))

    body = soup.find("body")
    if body:
        candidates.append(_clean_text(body.get_text(" ", strip=True)))

    merged = " ".join([c for c in candidates if c])
    if not merged:
        merged = _clean_text(soup.get_text(" ", strip=True))

    return merged[:max_chars]


def _is_naver_blog_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "blog.naver.com" in host or "m.blog.naver.com" in host


def _parse_naver_blog_ids(url: str) -> tuple[str | None, str | None]:
    """네이버 블로그 URL에서 blogId/logNo를 파싱한다."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    query = parse_qs(parsed.query)
    blog_id = query.get("blogId", [None])[0]
    log_no = query.get("logNo", [None])[0]

    if blog_id and log_no:
        return blog_id, log_no

    # /{blogId}/{logNo} 패턴
    path_parts = [p for p in parsed.path.split("/") if p]
    if ("blog.naver.com" in host or "m.blog.naver.com" in host) and len(path_parts) >= 2:
        maybe_blog_id = path_parts[0]
        maybe_log_no = path_parts[1]
        if maybe_log_no.isdigit():
            return maybe_blog_id, maybe_log_no

    return None, None


def _build_naver_mobile_post_url(url: str) -> str | None:
    blog_id, log_no = _parse_naver_blog_ids(url)
    if not blog_id or not log_no:
        return None
    return f"https://m.blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"


def _extract_naver_blog_text(html: str, max_chars: int) -> str:
    """네이버 블로그 페이지에서 본문 텍스트를 최대한 우선 추출한다."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    selectors = [
        "div.se-main-container",   # 신에디터
        "div#postViewArea",        # 구에디터
        "div.post_ct",             # 일부 모바일 템플릿
        "div#postListBody",
        "div#viewTypeSelector",
        "article",
        "body",
    ]

    candidates: list[str] = []
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        text = _clean_text(node.get_text(" ", strip=True))
        if text:
            candidates.append(text)

    if not candidates:
        return ""

    # 가장 긴 텍스트를 본문으로 간주
    return max(candidates, key=len)[:max_chars]


async def _fetch_naver_blog_text(
    client: httpx.AsyncClient, url: str, max_chars: int
) -> tuple[str, int]:
    """
    네이버 블로그 본문을 우선적으로 가져온다.
    1) 모바일 PostView URL 우선
    2) 원본 URL
    3) 원본 HTML 내 mainFrame iframe src 추적
    """
    candidate_urls: list[str] = []
    mobile_url = _build_naver_mobile_post_url(url)
    if mobile_url:
        candidate_urls.append(mobile_url)
    candidate_urls.append(url)

    last_status = 200
    for candidate in candidate_urls:
        resp = await client.get(candidate, follow_redirects=True)
        last_status = resp.status_code
        resp.raise_for_status()

        # 네이버 데스크탑 페이지는 mainFrame iframe 안에 본문이 있는 경우가 많다.
        soup = BeautifulSoup(resp.text, "lxml")
        frame = soup.find("iframe", id="mainFrame")
        if frame and frame.get("src"):
            frame_url = urljoin(str(resp.url), frame["src"])
            frame_resp = await client.get(frame_url, follow_redirects=True)
            last_status = frame_resp.status_code
            frame_resp.raise_for_status()
            extracted = _extract_naver_blog_text(frame_resp.text, max_chars=max_chars)
            if extracted:
                return extracted, frame_resp.status_code

        extracted = _extract_naver_blog_text(resp.text, max_chars=max_chars)
        if extracted:
            return extracted, resp.status_code

    return "", last_status


async def _fetch_one(client: httpx.AsyncClient, url: str, max_chars: int) -> dict[str, Any]:
    """단일 URL을 가져와 정규화된 결과 딕셔너리로 반환한다."""
    try:
        if _is_naver_blog_url(url):
            text, status_code = await _fetch_naver_blog_text(client, url, max_chars=max_chars)
        else:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            status_code = resp.status_code
            text = _extract_page_text(resp.text, max_chars=max_chars)
        if not text:
            return {
                "url": url,
                "success": False,
                "status_code": status_code,
                "text": "",
                "error": "본문 추출 실패",
            }
        return {
            "url": url,
            "success": True,
            "status_code": status_code,
            "text": text,
            "error": None,
        }
    except Exception as exc:
        logger.warning("블로그 크롤링 실패 (%s): %s", url, exc)
        return {
            "url": url,
            "success": False,
            "status_code": None,
            "text": "",
            "error": str(exc),
        }


async def crawl_blog_details(blog_urls: list[str]) -> list[dict[str, Any]]:
    """
    블로그 링크 목록을 비동기로 수집해 구조화된 결과를 반환한다.

    각 결과 항목:
    - url: 원본 URL
    - success: 수집 성공 여부
    - status_code: HTTP 상태 코드 (실패 시 None)
    - text: 추출 텍스트 (성공 시)
    - error: 오류 메시지 (실패 시)
    """
    if not blog_urls:
        logger.info("[crawl] 단계=details | 링크=0 → 스킵")
        return []

    settings = get_settings()
    urls = blog_urls[: settings.crawl_max_blog_links]
    logger.info(
        "[crawl] 단계=details_start | 요청_링크=%s (상한=%s) | 타임아웃=%ss | 페이지당_최대자수=%s",
        len(urls),
        settings.crawl_max_blog_links,
        settings.crawl_timeout_sec,
        settings.crawl_max_chars_per_page,
    )

    timeout = httpx.Timeout(settings.crawl_timeout_sec)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AniwhereBot/1.0; +https://aniwhere.local)"
    }

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        tasks = [
            _fetch_one(client, url=u, max_chars=settings.crawl_max_chars_per_page)
            for u in urls
        ]
        results = list(await asyncio.gather(*tasks))
    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    text_chars = sum(len(r.get("text") or "") for r in results if r.get("success"))
    logger.info(
        "[crawl] 단계=details_end | 성공=%s 실패=%s | 추출_총자수(성공분)=%s",
        ok,
        fail,
        text_chars,
    )
    for r in results:
        if r.get("success"):
            logger.debug(
                "[crawl] url=%s status=%s text_chars=%s",
                r.get("url"),
                r.get("status_code"),
                len(r.get("text") or ""),
            )
        else:
            logger.debug(
                "[crawl] url=%s 실패=%s",
                r.get("url"),
                r.get("error"),
            )
    return results


async def crawl_blog_context(blog_urls: list[str]) -> str:
    """
    블로그 링크 목록을 비동기로 수집하고 요약용 문맥 문자열로 합친다.

    - 링크 수 제한: settings.crawl_max_blog_links
    - 페이지별 최대 문자 수: settings.crawl_max_chars_per_page
    """
    details = await crawl_blog_details(blog_urls)
    if not details:
        logger.info("[crawl] 단계=context | 결과=빈_details → placeholder_문구_반환")
        return "수집된 블로그 본문 없음"

    chunks: list[str] = []
    for item in details:
        if item["success"]:
            chunks.append(f"[{item['url']}] {item['text']}")
        else:
            chunks.append(f"[{item['url']}] 접근 실패: {item['error']}")

    merged = "\n".join(chunks)
    logger.info(
        "[crawl] 단계=context_end | 합친_문맥_자수=%s | 블록수=%s",
        len(merged),
        len(chunks),
    )
    return merged
