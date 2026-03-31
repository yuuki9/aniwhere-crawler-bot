"""Gemini API 연동 서비스 계층.

추후 프롬프트 엔지니어링이 집중될 파일이다.
현재는 상점 이름·주소·SNS 링크를 기반으로 '어떤 상점인지' 요약을 요청하는
기본 흐름을 구현한다.
"""

import asyncio
import logging
from functools import lru_cache

import google.generativeai as genai

from app.core.config import get_settings
from app.core.exceptions import GeminiServiceError
from app.schemas.shop import ShopRecord
from app.schemas.summary import ShopSummary

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> genai.GenerativeModel:
    """싱글턴 패턴으로 GenerativeModel 인스턴스를 반환한다."""
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(
        model_name=settings.gemini_model,
        generation_config={
            "max_output_tokens": settings.gemini_max_output_tokens,
            "temperature": settings.gemini_temperature,
        },
    )


def _build_prompt(shop: ShopRecord) -> str:
    """
    단일 상점에 대한 요약 요청 프롬프트를 생성한다.

    [프롬프트 엔지니어링 포인트]
    - 역할 지정(Role): 가챠/피규어샵 큐레이터로 페르소나 고정
    - 출력 형식 강제: 3문장 이내 한국어 요약
    - 근거 명시: 제공된 링크 정보를 바탕으로 하도록 유도
    - Few-shot 예시 삽입이 필요하다면 이 함수 안에 추가할 것
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
아래 상점 정보를 참고하여 이 상점이 어떤 곳인지 한국어로 3문장 이내로 간결하게 요약해 주세요.
알 수 없는 정보는 추측하지 말고, 제공된 정보 범위 안에서만 설명하세요.

[상점 정보]
- 상점명: {shop.name}
- 주소: {shop.address}
- 블로그 링크:
{blog_links}
- SNS / 기타:
{sns_info}

[요약]"""


async def summarize_shop(shop: ShopRecord) -> ShopSummary:
    """단일 상점을 Gemini API로 비동기 요약한다."""
    model = _get_model()
    prompt = _build_prompt(shop)

    try:
        # google-generativeai 의 generate_content_async 사용
        response = await model.generate_content_async(prompt)
        summary_text = response.text.strip()
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
