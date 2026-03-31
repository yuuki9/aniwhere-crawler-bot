from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional


class ShopRecord(BaseModel):
    """CSV의 단일 행을 표현하는 모델."""

    address: str
    name: str
    px: float
    py: float
    blog: list[str] = []
    insta: Optional[str] = None
    x: Optional[str] = None
    place: Optional[str] = None
    homepage: Optional[str] = None

    @field_validator("blog", mode="before")
    @classmethod
    def parse_blog_links(cls, v: str | list) -> list[str]:
        """blog 컬럼의 컴마 구분 링크 문자열을 리스트로 파싱."""
        if isinstance(v, list):
            return [link.strip() for link in v if link.strip()]
        if isinstance(v, str):
            return [link.strip() for link in v.split(",") if link.strip()]
        return []

    @field_validator("px", "py", mode="before")
    @classmethod
    def coerce_float(cls, v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError) as e:
            raise ValueError(f"좌표값을 숫자로 변환할 수 없습니다: {v!r}") from e
