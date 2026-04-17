"""정제된 지식 텍스트를 ChromaDB에 임베딩·저장한다 (RAG 검색과 동일 컬렉션)."""

from __future__ import annotations

import logging

import chromadb
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_embedding_model: SentenceTransformer | None = None
_chroma_client: chromadb.PersistentClient | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info("[chroma] 임베딩 모델 로드: all-MiniLM-L6-v2")
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def _get_collection():
    global _chroma_client
    settings = get_settings()
    if _chroma_client is None:
        logger.info(
            "[chroma] PersistentClient 초기화 | persist_path=%s",
            settings.chroma_persist_path,
        )
        _chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_path)
    try:
        return _chroma_client.get_collection("shops")
    except Exception:
        logger.info("[chroma] 컬렉션 없음 → shops 생성")
        return _chroma_client.create_collection("shops")


def upsert_shop_knowledge(shop_id: int, text: str) -> None:
    """shop_id와 knowledge_base 텍스트로 벡터를 upsert한다."""
    if not text or not str(text).strip():
        logger.warning("[chroma] upsert 생략 | 이유=빈_텍스트 | shop_id=%s", shop_id)
        return
    logger.info(
        "[chroma] upsert 시작 | shop_id=%s | 문서_자수=%s",
        shop_id,
        len(text),
    )
    collection = _get_collection()
    model = _get_embedding_model()
    embedding = model.encode(text).tolist()
    sid = str(shop_id)
    metadata = {"shop_id": sid}
    upsert = getattr(collection, "upsert", None)
    if callable(upsert):
        upsert(
            ids=[sid],
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata],
        )
    else:
        try:
            collection.delete(ids=[sid])
        except Exception:
            pass
        collection.add(
            ids=[sid],
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata],
        )
    logger.info(
        "[chroma] upsert 완료 | shop_id=%s | 벡터_차원=%s",
        shop_id,
        len(embedding),
    )
