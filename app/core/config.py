from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    app_debug: bool = True

    # CSV Processing
    csv_batch_size: int = 100
    csv_max_file_size_mb: int = 50

    # Crawling
    crawl_timeout_sec: float = 10.0
    crawl_max_blog_links: int = 10
    crawl_max_chars_per_page: int = 3000

    # Naver Search API
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_blog_results_per_shop: int = 10

    # Gemini (정제용)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"

    # AWS Credentials
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_default_region: str = "ap-northeast-2"

    # MySQL
    mysql_host: str = "3.39.150.248"
    mysql_port: int = 25431
    mysql_user: str = "root"
    mysql_password: str = "aniwhere2026!"
    mysql_database: str = "aniwhere"

    # S3
    s3_bucket_name: str = "aniwhere-knowledge-base"

    # Output
    output_dir: str = "./output"

    # ChromaDB (RAG / 파이프라인 공통)
    chroma_persist_path: str = "chromadb"
    # RAG: Chroma 최상위 결과 거리가 이 값보다 크면(덜 유사하면) 컨텍스트 없이 Gemini만 사용.
    # None이면(기본) 빈 문서가 아닌 한 Chroma 결과를 항상 컨텍스트로 사용.
    rag_chroma_max_distance: float | None = None

    # 로컬 파이프라인 (run_pipeline.py)
    pipeline_sleep_sec: float = 15.0
    pipeline_max_blog_links_crawl: int = 5

    # TMDB v3 (AniList 응답에 한글 제목 보강) — 내부 데이터 구축용 기본 키; 배포 시 환경변수로 덮어쓰기 권장
    tmdb_api_key: str = "f1e4b3eb2c4842e70544eed062b139af"


@lru_cache
def get_settings() -> Settings:
    return Settings()
