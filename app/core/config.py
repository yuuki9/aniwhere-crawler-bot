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

    # Gemini
    gemini_api_key: str
    gemini_model: str = "gemini-flash-latest"
    gemini_max_output_tokens: int = 2048
    gemini_temperature: float = 0.3

    # CSV Processing
    csv_batch_size: int = 100
    csv_max_file_size_mb: int = 50

    # Crawling
    crawl_timeout_sec: float = 10.0
    crawl_max_blog_links: int = 3
    crawl_max_chars_per_page: int = 1500


@lru_cache
def get_settings() -> Settings:
    return Settings()
