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


async def search_shops(query: str, n_results: int = 3) -> dict:
    """
    RAG 검색: 쿼리 → 유사 상점 검색 → Gemini 답변 생성
    
    Args:
        query: 사용자 질문 (예: "홍대 진격의 거인")
        n_results: 반환할 상점 수
    
    Returns:
        {
            "query": "홍대 진격의 거인",
            "shops": [...],
            "answer": "..."
        }
    """
    # 1. 쿼리 임베딩
    logger.info("[rag] 단계=embed_query | n_results=%s | query_len=%s", n_results, len(query))
    model = get_embedding_model()
    query_embedding = model.encode(query).tolist()

    # 2. ChromaDB 검색
    collection = get_chroma_collection()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )
    logger.info(
        "[rag] 단계=chroma_query | 반환_문서수=%s",
        len(results.get("documents", [[]])[0] or []),
    )

    # 3. 검색 결과 정리
    shops = []
    context = ""
    for i, (doc, metadata) in enumerate(zip(results['documents'][0], results['metadatas'][0]), 1):
        shops.append({
            'shop_id': metadata['shop_id'],
            'content': doc
        })
        context += f"\n\n[상점 {i}]\n{doc}"

    logger.info(
        "[rag] 단계=context | shop_ids=%s | context_chars=%s",
        [s["shop_id"] for s in shops],
        len(context),
    )

    # 4. Gemini로 답변 생성 (프롬프트 가드레일 포함)
    logger.info("[rag] 단계=gemini_generate | model=%s", settings.gemini_model)
    client = get_gemini_client()
    prompt = f"""당신은 서울 48개 피규어/애니메이션 굿즈샵 안내 전문 AI입니다.

[중요 규칙]
1. 피규어/애니메이션/굿즈/가챠 관련 질문만 답변하세요
2. 정치/종교/성인 콘텐츠 질문은 "피규어샵 관련 질문만 답변 가능합니다"라고 응답하세요
3. 제공된 상점 정보에 없는 내용은 추측하지 마세요
4. 상점명, 주소, 특징을 정확히 전달하세요

사용자 질문: {query}

관련 상점 정보:{context}

위 정보를 바탕으로 사용자 질문에 친절하게 답변해주세요.
- 상점명, 주소, 특징을 포함하세요
- 여러 상점이 있으면 모두 소개하세요
- 자연스러운 한국어로 작성하세요"""
    
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=prompt
    )
    
    answer = response.text.strip() if response.text else "답변을 생성할 수 없습니다."
    logger.info("[rag] 단계=완료 | answer_chars=%s", len(answer))

    return {
        "query": query,
        "shops": shops,
        "answer": answer
    }
