"""S3 텍스트 파일을 ChromaDB에 임베딩하여 저장"""

import asyncio
import boto3
from sentence_transformers import SentenceTransformer
import chromadb
from app.core.config import get_settings

settings = get_settings()


def init_chromadb():
    """ChromaDB 클라이언트 초기화"""
    client = chromadb.PersistentClient(path=settings.chroma_persist_path)
    try:
        client.delete_collection("shops")
        print("기존 컬렉션 삭제")
    except:
        pass
    collection = client.create_collection("shops")
    return collection


def download_s3_files():
    """S3에서 모든 shop 텍스트 파일 다운로드"""
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
    
    return files


def embed_and_store():
    """임베딩 생성 및 ChromaDB 저장"""
    print("=" * 80)
    print("S3 → ChromaDB 임베딩 시작")
    print("=" * 80)
    
    # 1. ChromaDB 초기화
    print("\n1. ChromaDB 초기화...")
    collection = init_chromadb()
    
    # 2. S3 파일 다운로드
    print("\n2. S3 파일 다운로드...")
    files = download_s3_files()
    print(f"   다운로드 완료: {len(files)}개 파일")
    
    # 3. 임베딩 모델 로드 (무료)
    print("\n3. 임베딩 모델 로드...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    print("   모델 로드 완료")
    
    # 4. 임베딩 생성 및 저장
    print("\n4. 임베딩 생성 및 저장...")
    for i, file in enumerate(files, 1):
        embedding = model.encode(file['text']).tolist()
        collection.add(
            documents=[file['text']],
            embeddings=[embedding],
            ids=[file['id']],
            metadatas=[{'shop_id': file['id']}]
        )
        print(f"   [{i}/{len(files)}] shop_{file['id']}.txt 완료")
    
    print("\n" + "=" * 80)
    print(f"임베딩 완료: {len(files)}개 상점")
    print("=" * 80)


if __name__ == "__main__":
    embed_and_store()
