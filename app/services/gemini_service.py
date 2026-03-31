"""Gemini API 연동 서비스 계층.

추후 프롬프트 엔지니어링이 집중될 파일이다.
현재는 상점 이름·주소·SNS 링크를 기반으로 '어떤 상점인지' 요약을 요청하는
기본 흐름을 구현한다.
"""

import asyncio
import logging
import re
from functools import lru_cache

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.schemas.shop import ShopRecord
from app.schemas.summary import ShopSummary
from app.services.blog_crawl_service import crawl_blog_context

logger = logging.getLogger(__name__)
_MULTI_SPACE = re.compile(r"\s+")
_JSON_LIKE = re.compile(r"\{[^{}]{20,}\}")
_NOISE_PATTERNS = [
    "본문 바로가기",
    "블로그 카테고리 이동",
    "검색 MY메뉴 열기",
    "이웃추가",
    "본문 기타 기능",
    "본문 폰트 크기 조정",
    "URL복사",
    "신고하기",
]
_ANIME_KEYWORDS = [
    "하이큐",
    "귀멸의 칼날",
    "주술회전",
    "헌터헌터",
    "나히아",
    "나의 히어로 아카데미아",
    "원피스",
    "나루토",
    "에반게리온",
    "프리렌",
    "봇치",
    "도쿄 리벤저스",
]


def _is_acceptable_summary(text: str) -> bool:
    """요약 결과가 길이/형식 기준을 만족하는지 검사한다."""
    if len(text) < 700:
        return False
    required_tokens = ["강점", "단점", "취사선택", "애니"]
    if not all(token in text for token in required_tokens):
        return False
    return True


def _compress_crawled_context(raw: str, max_chars: int = 900) -> str:
    """크롤링 원문에서 UI 노이즈를 줄이고 Gemini 입력 길이를 압축한다."""
    text = raw
    for token in _NOISE_PATTERNS:
        text = text.replace(token, " ")
    text = _JSON_LIKE.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text[:max_chars]


def _extract_evidence_from_crawl(crawled_text: str) -> str:
    """크롤링 본문에서 모델에 전달할 핵심 근거만 압축한다."""
    found = [k for k in _ANIME_KEYWORDS if k in crawled_text]
    found_str = ", ".join(dict.fromkeys(found)) if found else "명시적으로 식별된 작품 없음"

    signal_tokens = []
    for token in ["가챠", "피규어", "랜덤", "굿즈", "아크릴", "인형", "제일복권"]:
        if token in crawled_text:
            signal_tokens.append(token)
    signal_str = ", ".join(signal_tokens) if signal_tokens else "카테고리 신호 약함"

    return (
        f"- 관찰된 작품 키워드: {found_str}\n"
        f"- 관찰된 상품/카테고리 키워드: {signal_str}\n"
        f"- 본문 발췌(노이즈 제거): {crawled_text[:500]}"
    )


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    """싱글턴 패턴으로 GenAI Client 인스턴스를 반환한다."""
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def _build_prompt(shop: ShopRecord, crawl_evidence: str) -> str:
    """
    단일 상점에 대한 요약 요청 프롬프트를 생성한다.

    [프롬프트 엔지니어링 포인트]
    - 역할 지정(Role): 가챠/피규어샵 큐레이터
    - 출력 형식 강제: 한국어 800~1200자
    - 의사결정 지원: 취사선택 포인트 + 강점/단점 포함
    - 근거 명시: 크롤링 본문 기반 추론 (불확실하면 완곡하게)
    """
    blog_links = "\n".join(f"  - {url}" for url in shop.blog) if shop.blog else "  (없음)"
    sns_parts = []
    if shop.insta:
        sns_parts.append(f"인스타그램: {shop.insta}")
    if shop.x:
        sns_parts.append(f"X(트위터): {shop.x}")
    if shop.place:
        sns_parts.append(f"네이버 플레이스: {shop.place}")
    if shop.homepage:
        sns_parts.append(f"홈페이지: {shop.homepage}")
    sns_info = "\n".join(f"  - {s}" for s in sns_parts) if sns_parts else "  (없음)"

    return f"""당신은 가챠/피규어샵 전문 큐레이터입니다.
아래 정보를 바탕으로 사용자가 방문 여부를 결정할 수 있게 한국어로 자세히 정리하세요.
분량은 반드시 800~1200자로 작성하세요.

[출력 규칙]
1) 반드시 아래 섹션 제목을 그대로 사용하세요.
- 상점 요약
- 관찰된 애니/굿즈 종류
- 취사선택 포인트
- 강점
- 단점/주의점
- 총평
2) "관찰된 애니/굿즈 종류"에는 크롤링 텍스트에서 확인 가능한 작품/카테고리만 쓰세요.
3) "취사선택 포인트"에는 어떤 사용자에게 추천/비추천되는지 구체적으로 쓰세요.
4) 강점은 최소 3개, 단점/주의점은 최소 2개를 bullet로 쓰세요.
5) 알 수 없는 정보는 추측하지 말고, 불확실하면 "추정"이라고 표시하세요.
6) 문장은 끝까지 완결되게 작성하고 중간에 끊기지 않게 하세요.

[상점 정보]
- 상점명: {shop.name}
- 주소: {shop.address}
- 블로그 링크:
{blog_links}
- SNS / 기타:
{sns_info}
- 블로그 크롤링 핵심 근거:
{crawl_evidence}

[요약]"""


async def summarize_shop(shop: ShopRecord) -> ShopSummary:
    """단일 상점을 Gemini API로 비동기 요약한다."""
    client = _get_client()
    settings = get_settings()
    crawled_blog_context = _compress_crawled_context(await crawl_blog_context(shop.blog))
    crawl_evidence = _extract_evidence_from_crawl(crawled_blog_context)
    prompt = _build_prompt(shop, crawl_evidence=crawl_evidence)

    try:
        summary_candidates: list[str] = []
        attempt_prompts = [
            prompt,
            (
                f"{prompt}\n\n"
                "추가 지시: 분량이 부족합니다. 반드시 800~1200자 범위를 만족하고, "
                "모든 섹션 제목을 포함하세요."
            ),
            (
                f"{prompt}\n\n"
                "최종 지시: 마크다운 섹션 구조를 유지하고, "
                "강점 3개 이상/단점 2개 이상을 반드시 포함하세요."
            ),
        ]

        for attempt_prompt in attempt_prompts:
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=attempt_prompt,
                config=types.GenerateContentConfig(
                    temperature=settings.gemini_temperature,
                    max_output_tokens=settings.gemini_max_output_tokens,
                ),
            )
            text = (response.text or "").strip()
            summary_candidates.append(text)
            if _is_acceptable_summary(text):
                break

        summary_text = max(
            summary_candidates,
            key=lambda s: (
                _is_acceptable_summary(s),
                len(s),
                s.endswith((".", "!", "?", "다", "요")),
            ),
        )
        if not _is_acceptable_summary(summary_text):
            # 긴 크롤링 원문을 다시 붙이지 않고 "초안 확장"만 요청해 길이 부족 현상을 줄인다.
            for _ in range(2):
                expand_prompt = (
                    "[재작성 지시]\n"
                    "아래 초안은 정보가 부족하고 중간에 끊겼습니다. 같은 사실 범위 안에서 내용을 확장해 "
                    "반드시 800~1200자 분량으로 완결된 문서를 작성하세요.\n\n"
                    "필수 섹션:\n"
                    "- 상점 요약\n"
                    "- 관찰된 애니/굿즈 종류\n"
                    "- 취사선택 포인트\n"
                    "- 강점\n"
                    "- 단점/주의점\n"
                    "- 총평\n\n"
                    f"[초안]\n{summary_text}"
                )
                expand_response = await client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=expand_prompt,
                    config=types.GenerateContentConfig(
                        temperature=settings.gemini_temperature,
                        max_output_tokens=settings.gemini_max_output_tokens,
                    ),
                )
                expanded = (expand_response.text or "").strip()
                if len(expanded) > len(summary_text):
                    summary_text = expanded
                if _is_acceptable_summary(summary_text):
                    break
    except Exception as exc:
        logger.error("Gemini 요약 실패 (shop=%s): %s", shop.name, exc)
        return ShopSummary(name=shop.name, address=shop.address, summary="", error=str(exc))

    return ShopSummary(name=shop.name, address=shop.address, summary=summary_text)


async def summarize_shops_batch(
    shops: list[ShopRecord],
    concurrency: int = 5,
) -> list[ShopSummary]:
    """
    여러 상점을 concurrency 단위로 병렬 요약한다.

    asyncio.Semaphore로 동시 요청 수를 제한하여 Gemini API Rate Limit을 준수한다.
    concurrency 값은 Gemini 무료 티어(15 RPM)에 맞춰 보수적으로 설정한다.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _guarded(shop: ShopRecord) -> ShopSummary:
        async with semaphore:
            return await summarize_shop(shop)

    results = await asyncio.gather(*[_guarded(s) for s in shops], return_exceptions=False)
    return list(results)
