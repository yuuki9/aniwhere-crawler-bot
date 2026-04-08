"""크롤링 원문을 Gemini Flash로 정제하는 서비스.

출력:
- RDB 저장용 JSON (shops, shop_details, categories, works 테이블 매핑)
- Knowledge Base용 자연어 텍스트 (.txt)
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.schemas.shop import ShopRecord

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """당신은 피규어/가챠샵 데이터 정제 전문가입니다.
아래 상점 정보와 블로그 크롤링 원문을 분석해 두 가지 형식으로 출력하세요.

[상점 기본 정보]
- 상점명: {name}
- 주소: {address}
- 경도(px): {px}
- 위도(py): {py}

[블로그 크롤링 원문]
{crawl_text}

---

[출력 규칙]
반드시 아래 JSON 구조 하나만 출력하세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요.

{{
  "rdb": {{
    "name": "상점명",
    "address": "주소",
    "px": 0.0,
    "py": 0.0,
    "floor": "층수 또는 null",
    "region": "지역명 (홍대/강남/신촌 등, 판단 불가시 null)",
    "status": "active 또는 unverified",
    "categories": ["가챠", "피규어"],
    "works": ["귀멸의 칼날", "주술회전"],
    "congestion": "low 또는 medium 또는 high 또는 null",
    "visit_tip": "방문 팁 한 줄 또는 null",
    "links": [
      {{"type": "blog", "url": "https://..."}}
    ]
  }},
  "knowledge_base_text": "상점명: ...\\n주소: ...\\n\\n취급 상품: ...\\n관련 작품: ...\\n특징: ...\\n\\n블로그 출처 요약:\\n- ...\\n- ..."
}}

알 수 없는 정보는 null 또는 빈 배열로 처리하세요. 추측하지 마세요."""


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    return genai.Client(api_key=get_settings().gemini_api_key)


async def refine_shop(shop: ShopRecord, crawl_text: str) -> dict:
    """
    단일 상점의 크롤링 원문을 Gemini Flash로 정제한다.

    반환값:
    {
        "rdb": { ... },                  # DB 저장용
        "knowledge_base_text": "...",    # S3 업로드용 텍스트
        "error": None | "오류 메시지"
    }
    """
    settings = get_settings()
    prompt = _PROMPT_TEMPLATE.format(
        name=shop.name,
        address=shop.address,
        px=shop.px,
        py=shop.py,
        crawl_text=crawl_text[:3000],
    )

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )
        text = (response.text or "").strip()
        # JSON 파싱
        result = json.loads(text)
        result["error"] = None
        return result
    except Exception as e:
        logger.error("정제 실패 (shop=%s): %s", shop.name, e)
        return {"rdb": None, "knowledge_base_text": None, "error": str(e)}


def save_knowledge_base_doc(shop_name: str, text: str, output_dir: str) -> Path:
    """Knowledge Base용 .txt 파일을 저장한다."""
    dir_path = Path(output_dir) / "knowledge_base"
    dir_path.mkdir(parents=True, exist_ok=True)

    # 파일명에 사용할 수 없는 문자 제거
    safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in shop_name).strip()
    file_path = dir_path / f"{safe_name}.txt"
    file_path.write_text(text, encoding="utf-8")
    return file_path
