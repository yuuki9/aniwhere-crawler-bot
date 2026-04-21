"""RAG 검색 서비스: ChromaDB + Gemini"""

import logging

import chromadb
from sentence_transformers import SentenceTransformer
from google import genai
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 전역 변수
_chroma_client = None
_embedding_model = None
_gemini_client = None


def get_chroma_collection():
    """ChromaDB 컬렉션 가져오기"""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_path)
    return _chroma_client.get_collection("shops")


def get_embedding_model():
    """임베딩 모델 가져오기"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model


def get_gemini_client():
    """Gemini 클라이언트 가져오기"""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


def _shops_non_empty(shops: list) -> bool:
    return bool(shops) and any((s.get("content") or "").strip() for s in shops)


# Gemini 프롬프트 내 거절 규칙 한 덩어리 (100자 미만)
_RAG_REJECT_GUIDE = (
    "정치·종교·법·의료·투자·IT·날씨·부동산·일상·무관 연예 등 비애니·배송·음란은 거절, "
    "해당 시 짧게 거절 후 예시 질문 제안."
)


def _prompt_chroma_rag(query: str, context: str) -> str:
    return f"""애니·굿즈 안내 AI. 캐릭터·작품·굿즈·문서에 있는 매장·주소만. 없는 매장·주소 금지. 배송 안내 금지.
[거절] {_RAG_REJECT_GUIDE}

질문: {query}
[참고 문서]{context}
문서 우선, 한국어로 답변."""


def _prompt_gemini_only(query: str) -> str:
    return f"""애니·굿즈 안내 AI. 캐릭터·작품·굿즈 일반지식만. DB 없는 매장 주소·재고 단정 금지. 배송 안내 금지.
[거절] {_RAG_REJECT_GUIDE}

질문: {query}
KB 없음, 일반지식만. 한국어로 답변."""


async def search_shops(query: str) -> dict:
    """
    RAG 검색: 쿼리 → ChromaDB 전체 문서 유사도 순 → (걸리는 문서만) Gemini

    `RAG_CHROMA_MAX_DISTANCE`가 설정된 경우 거리가 그 이하인 문서만 shops·컨텍스트에 포함.

    Returns:
        query, document_ids, shops, answer, chroma_used
    """
    # 1. 쿼리 임베딩
    logger.info("[rag] 단계=embed_query | query_len=%s", len(query))
    model = get_embedding_model()
    query_embedding = model.encode(query).tolist()

    # 2. ChromaDB: 컬렉션 전체를 유사도 순으로 조회 (상한 없음 — 문서 수만큼)
    collection = get_chroma_collection()
    n_total = collection.count()
    if n_total <= 0:
        row_docs, row_metas, row_ids, row_dist = [], [], [], []
    else:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_total,
        )
        row_docs = results["documents"][0]
        row_metas = results["metadatas"][0]
        row_ids = results.get("ids", [[]])[0] or []
        row_dist = (results.get("distances") or [[]])[0]

    logger.info("[rag] 단계=chroma_query | 컬렉션=%s | 반환_문서수=%s", n_total, len(row_docs))

    # 3. 검색 결과 정리 (Chroma 문서 id = upsert 시 사용한 id, shop_id 문자열과 동일)
    shops: list[dict] = []
    for i, doc in enumerate(row_docs):
        metadata = row_metas[i]
        chroma_id = row_ids[i] if i < len(row_ids) else str(metadata.get("shop_id", ""))
        dist = row_dist[i] if row_dist is not None and i < len(row_dist) else None
        shops.append({
            "document_id": chroma_id,
            "shop_id": metadata["shop_id"],
            "distance": dist,
            "content": doc,
        })

    max_d = settings.rag_chroma_max_distance
    if max_d is not None:
        before = len(shops)
        shops = [
            s
            for s in shops
            if s["distance"] is None or float(s["distance"]) <= max_d
        ]
        logger.info(
            "[rag] 단계=chroma_filter | max_distance=%s | 유지=%s/%s",
            max_d,
            len(shops),
            before,
        )

    document_ids: list[str] = []
    context = ""
    for i, s in enumerate(shops):
        document_ids.append(s["document_id"])
        context += f"\n\n[상점 {i + 1} | 문서 id={s['document_id']}]\n{s['content']}"

    chroma_used = _shops_non_empty(shops)
    if not chroma_used:
        context = ""
        shops = []
        document_ids = []

    logger.info(
        "[rag] 단계=context | chroma_used=%s | document_ids=%s | context_chars=%s",
        chroma_used,
        document_ids,
        len(context),
    )

    # 4. Gemini
    logger.info(
        "[rag] 단계=gemini_generate | model=%s | mode=%s",
        settings.gemini_model,
        "chroma_rag" if chroma_used else "gemini_only",
    )
    client = get_gemini_client()
    prompt = _prompt_chroma_rag(query, context) if chroma_used else _prompt_gemini_only(query)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=prompt
    )

    answer = response.text.strip() if response.text else "답변을 생성할 수 없습니다."
    logger.info("[rag] 단계=완료 | answer_chars=%s", len(answer))

    return {
        "query": query,
        "chroma_used": chroma_used,
        "document_ids": document_ids,
        "shops": shops,
        "answer": answer,
    }
