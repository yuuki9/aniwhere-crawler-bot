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
    gemini_model: str = "gemini-2.0-flash"

    # Output
    output_dir: str = "./output"


@lru_cache
def get_settings() -> Settings:
    return Settings()
