"""크롤링 원문을 Gemini Flash로 정제하는 서비스.

출력:
- RDB 저장용 JSON (shops, shop_details, categories, work_ids → shop_works 매핑)
- Knowledge Base용 자연어 텍스트 (.txt)
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.schemas.shop import ShopRecord
from app.services.works_catalog_snapshot import (
    CatalogWorkLine,
    catalog_lines_to_json_blob,
    filter_work_ids,
    merge_work_id_lists,
)

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """당신은 피규어/가챠샵 데이터 정제 전문가입니다.
아래 상점 정보와 블로그 크롤링 원문을 철저히 분석해 JSON으로 출력하세요.

[상점 기본 정보]
- 상점명: {name}
- 주소: {address}
- 경도(px): {px}
- 위도(py): {py}

[블로그 크롤링 원문]
{crawl_text}

{catalog_section}

---

[분석 지침]
1. 블로그 원문에서 언급된 애니메이션/만화 **작품**을 파악하되, 작품과 매장을 연결할 때는 **아래에 제공된 카탈로그가 있으면 그 카탈로그에 나온 정수 id만** `rdb.work_ids`에 넣으세요. 카탈로그가 없거나 빈 안내인 경우 `work_ids`는 빈 배열 `[]`입니다.
2. 블로그 원문에서 언급된 모든 캐릭터명을 빠짐없이 추출하세요.
3. 상점의 카테고리(가챠, 피규어, 프라모델, 넨도로이드, 굿즈, 랜덤박스, 포토카드, 키링, 아크릴스탠드 등)를 모두 추출하세요.
4. 상점 특징, 분위기, 가격대, **제일복권(이치방쿠지) 취급 여부**, **방문 팁(시간대·혼잡·주의사항 등)** 을 반영하세요.

[출력 규칙]
반드시 아래 JSON 구조만 출력하세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요.
문자열 안에 줄바꿈이 필요하면 공백으로 대체하세요.

[가챠·피규어·애니 굿즈 매장 관련 여부]
- 블로그 원문이 가챠·피규어·애니메이션 굿즈·프라모델·넨도로이드 등 **이런 매장을 소개하는 내용이 아니면** (예: 무관한 맛집/카페/일반 후기만, 엉뚱한 주제):
  "is_figure_relevant": false,
  "rdb": null,
  "knowledge_base_text": null
  만 출력하세요. 추측으로 내용을 채우지 마세요.
- 가챠/피규어·굿즈 매장 소개에 해당하면 "is_figure_relevant": true 이고 아래 rdb·knowledge_base_text를 채웁니다.

[knowledge_base_text 규칙 (is_figure_relevant가 true일 때만)]
- 도로명·지번·층·건물명·역 출구·「oo로/oo길/oo구」 등 **주소·위치를 특정하는 문구는 절대 넣지 마세요.**
- 취급 상품·작품·캐릭터·가격대·분위기·방문 시 알면 좋은 점 등 **매장 특성**만 3~5문장으로 요약하세요.
- rdb 의 "visit_tip" 은 방문 팁을 **한 줄~짧은 문단**으로 구조화한 값이고, knowledge_base_text 와 중복돼도 됩니다( KB 는 더 긴 서술).
- rdb 쪽 "address" 필드는 CSV 기준 정제용이므로 knowledge_base_text 와 별개입니다.

{{
  "is_figure_relevant": true,
  "rdb": {{
    "name": "상점명",
    "address": "주소",
    "px": 0.0,
    "py": 0.0,
    "floor": "층수 또는 null",
    "region": "지역명 (홍대/강남/신촌/건대/이태원 등, 판단 불가시 null)",
    "status": "active 또는 unverified",
    "categories": ["가챠", "피규어", "굿즈", "프라모델"],
    "work_ids": [101, 205],
    "characters": ["탄지로", "고죠 사토루", "루피"],
    "sells_ichiban_kuji": "제일복권(이치방쿠지) 취급이면 true, 원문상 미취급·반대 증거면 false, 알 수 없으면 null",
    "visit_tip": "방문 팁 요약(평일 추천·혼잡 시간대·예약·준비물 등). 원문에 없으면 null",
    "links": [
      {{"type": "blog", "url": "https://..."}}
    ]
  }},
  "knowledge_base_text": "주소·위치 없이, 취급 상품·작품·캐릭터·가격대·분위기·특징만 3~5문장 요약"
}}

알 수 없는 정보는 null 또는 빈 배열로 처리하세요."""


_NO_CATALOG_SECTION = """[작품 카탈로그]
이 요청에는 작품 id 목록이 포함되어 있지 않습니다. `rdb.work_ids`는 반드시 빈 배열 `[]`로 두세요."""


def _catalog_section_chunk(chunk_index: int, n_chunks: int, blob: str) -> str:
    return (
        f"[작품 카탈로그 — 청크 {chunk_index + 1}/{n_chunks}]\n"
        "아래 JSON 배열의 각 원소는 id(MySQL works PK)와 titles(표시·검색용 제목 후보)입니다.\n"
        "블로그 원문에서 **실제로 취급·언급되는 작품**에 해당하는 id만 `rdb.work_ids`에 넣으세요. "
        "확신 없으면 생략(해당 id 미포함)합니다. **목록에 없는 id를 만들어내지 마세요.**\n\n"
        f"{blob}"
    )


def _strip_markdown_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


async def _gemini_generate_json(
    prompt: str,
    *,
    shop_label: str,
    max_output_tokens: int,
) -> dict:
    settings = get_settings()
    logger.info(
        "[refine] 단계=gemini_request | shop=%s | model=%s | prompt_chars=%s | max_out=%s",
        shop_label,
        settings.gemini_model,
        len(prompt),
        max_output_tokens,
    )
    client = _get_client()
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=max_output_tokens,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini 빈 응답")
    logger.debug("[refine] Gemini 원응답_자수=%s shop=%s", len(text), shop_label)
    cleaned = _strip_markdown_json(text)
    return json.loads(cleaned)


def _finalize_refine_result(result: dict, shop: ShopRecord) -> dict:
    if result.get("is_figure_relevant") is False:
        result["rdb"] = None
        result["knowledge_base_text"] = None
    elif result.get("rdb") is None:
        result["knowledge_base_text"] = None
    result["error"] = None
    kb = result.get("knowledge_base_text") or ""
    kb_len = len(str(kb).strip()) if kb else 0
    rdb = result.get("rdb")
    logger.info(
        "[refine] 단계=parse_ok | shop=%s | is_figure_relevant=%s | rdb=%s | kb_chars=%s",
        shop.name,
        result.get("is_figure_relevant"),
        "있음" if isinstance(rdb, dict) else "없음",
        kb_len,
    )
    return result


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    return genai.Client(api_key=get_settings().gemini_api_key)


async def refine_shop(shop: ShopRecord, crawl_text: str) -> dict:
    """
    단일 상점의 크롤링 원문을 Gemini Flash로 정제한다.

    카탈로그 없이 호출되므로 `work_ids`는 항상 빈 배열을 기대한다.
    """
    return await refine_shop_with_catalog(
        shop,
        crawl_text,
        [],
        allowed_work_ids=set(),
    )


async def refine_shop_with_catalog(
    shop: ShopRecord,
    crawl_text: str,
    catalog_chunks: list[list[CatalogWorkLine]],
    *,
    allowed_work_ids: set[int],
) -> dict:
    """
    카탈로그 청크가 있으면 청크 0에서 전체 rdb JSON을 받고, 추가 청크에서는 work_ids만 보강한다.
    catalog_chunks가 비면 카탈로그 없이 1회 호출(work_ids는 []).
    """
    shop_label = shop.name

    def chunk_prompt_extra(idx: int) -> str:
        if not catalog_chunks:
            return _NO_CATALOG_SECTION
        blob = catalog_lines_to_json_blob(catalog_chunks[idx])
        return _catalog_section_chunk(idx, len(catalog_chunks), blob)

    try:
        # --- 청크 0 (또는 단일 호출): 전체 스키마 ---
        prompt0 = _PROMPT_TEMPLATE.format(
            name=shop.name,
            address=shop.address,
            px=shop.px,
            py=shop.py,
            crawl_text=crawl_text,
            catalog_section=chunk_prompt_extra(0) if catalog_chunks else _NO_CATALOG_SECTION,
        )
        base = await _gemini_generate_json(
            prompt0,
            shop_label=shop_label,
            max_output_tokens=65536,
        )
        base = _finalize_refine_result(base, shop)

        per_chunk_ids: list[list[int]] = []
        rdb0 = base.get("rdb")
        if isinstance(rdb0, dict):
            raw_ids = rdb0.get("work_ids")
            per_chunk_ids.append(filter_work_ids(raw_ids, allowed_work_ids))

        # 비관련 매장이면 추가 카탈로그 호출 생략
        if base.get("is_figure_relevant") is False or not catalog_chunks or len(catalog_chunks) <= 1:
            if isinstance(base.get("rdb"), dict):
                base["rdb"]["work_ids"] = merge_work_id_lists(per_chunk_ids)
            return base

        # --- 추가 청크: work_ids 만 ---
        for k in range(1, len(catalog_chunks)):
            blob = catalog_lines_to_json_blob(catalog_chunks[k])
            extra_prompt = f"""당신은 피규어/가챠샵 데이터 보조 추출기입니다. 동일 상점·동일 블로그 원문에 대해 **추가 작품 카탈로그 청크**만 검토합니다.

[상점 기본 정보]
- 상점명: {shop.name}
- 주소: {shop.address}
- 경도(px): {shop.px}
- 위도(py): {shop.py}

[블로그 크롤링 원문]
{crawl_text}

[작품 카탈로그 — 청크 {k + 1}/{len(catalog_chunks)}]
아래 JSON 배열의 각 원소는 id(MySQL works PK)와 titles입니다.
블로그에서 **실제 취급·언급**이 확실한 작품 id만 고르세요. 확신 없으면 빈 배열.

{blob}

[출력]
순수 JSON 한 개만 출력하세요. 마크다운 코드블록 금지.
형식: {{"work_ids": [<정수>, ...]}}
목록에 없는 id를 출력하지 마세요.
"""
            try:
                parsed = await _gemini_generate_json(
                    extra_prompt,
                    shop_label=shop_label,
                    max_output_tokens=2048,
                )
                ids = filter_work_ids(parsed.get("work_ids"), allowed_work_ids)
                per_chunk_ids.append(ids)
            except Exception as e:
                logger.warning(
                    "[refine] 추가 청크 실패 shop=%s chunk=%s/%s | %s",
                    shop_label,
                    k + 1,
                    len(catalog_chunks),
                    e,
                )

        if isinstance(base.get("rdb"), dict):
            base["rdb"]["work_ids"] = merge_work_id_lists(per_chunk_ids)
        return base

    except Exception as e:
        logger.error("[refine] 단계=실패 | shop=%s | %s", shop.name, e)
        return {"rdb": None, "knowledge_base_text": None, "error": str(e)}


def save_knowledge_base_doc(shop_name: str, text: str, output_dir: str) -> Path:
    """Knowledge Base용 .txt 파일을 저장한다."""
    dir_path = Path(output_dir) / "knowledge_base"
    dir_path.mkdir(parents=True, exist_ok=True)

    # 파일명에 사용할 수 없는 문자 제거
    safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in shop_name).strip()
    file_path = dir_path / f"{safe_name}.txt"
    file_path.write_text(text, encoding="utf-8")
    logger.info(
        "[refine] 단계=kb_txt_saved | shop=%r | path=%s | 자수=%s",
        shop_name,
        file_path,
        len(text),
    )
    return file_path
