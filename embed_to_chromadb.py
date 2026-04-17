"""S3 텍스트 파일을 ChromaDB에 임베딩하여 저장"""

import logging

import boto3
import chromadb
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


def init_chromadb():
    """ChromaDB 클라이언트 초기화"""
    logger.info("[embed_s3] Chroma 초기화 | persist_path=%s", settings.chroma_persist_path)
    client = chromadb.PersistentClient(path=settings.chroma_persist_path)
    try:
        client.delete_collection("shops")
        logger.info("[embed_s3] 기존 컬렉션 shops 삭제")
    except Exception as e:
        logger.debug("[embed_s3] 컬렉션 삭제 스킵: %s", e)
    collection = client.create_collection("shops")
    return collection


def download_s3_files():
    """S3에서 모든 shop 텍스트 파일 다운로드"""
    logger.info(
        "[embed_s3] S3 목록 조회 | bucket=%s prefix=shops/",
        settings.s3_bucket_name,
    )
    s3 = boto3.client(
        's3',
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key
    )
    
    response = s3.list_objects_v2(
        Bucket=settings.s3_bucket_name,
        Prefix='shops/'
    )
    
    files = []
    for obj in response.get('Contents', []):
        key = obj['Key']
        if key.endswith('.txt'):
            shop_id = key.split('_')[1].split('.')[0]
            content = s3.get_object(Bucket=settings.s3_bucket_name, Key=key)
            text = content['Body'].read().decode('utf-8')
            files.append({'id': shop_id, 'text': text})

    logger.info("[embed_s3] S3 다운로드 완료 | txt_파일=%s", len(files))
    return files


def embed_and_store():
    """임베딩 생성 및 ChromaDB 저장"""
    logger.info("[embed_s3] S3 → Chroma 임베딩 시작")

    collection = init_chromadb()
    files = download_s3_files()

    logger.info("[embed_s3] 임베딩 모델 로드: all-MiniLM-L6-v2")
    model = SentenceTransformer('all-MiniLM-L6-v2')

    for i, file in enumerate(files, 1):
        embedding = model.encode(file['text']).tolist()
        collection.add(
            documents=[file['text']],
            embeddings=[embedding],
            ids=[file['id']],
            metadatas=[{'shop_id': file['id']}]
        )
        logger.info(
            "[embed_s3] %s/%s | shop_id=%s | 문서자수=%s 벡터차원=%s",
            i,
            len(files),
            file['id'],
            len(file['text']),
            len(embedding),
        )

    logger.info("[embed_s3] 전체 완료 | 상점=%s", len(files))


if __name__ == "__main__":
    embed_and_store()
