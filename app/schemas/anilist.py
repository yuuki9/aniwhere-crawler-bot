"""AniList GraphQL 응답 모델 (OpenAPI 스키마용)"""

from pydantic import BaseModel, Field, field_validator


class AnilistTitle(BaseModel):
    romaji: str | None = None
    english: str | None = None
    native: str | None = None


class AnilistCoverImage(BaseModel):
    extraLarge: str | None = None
    large: str | None = None
    color: str | None = Field(None, description="UI용 대표 색(HEX 등)")


class AnilistMedia(BaseModel):
    id: int
    idMal: int | None = Field(None, description="MyAnimeList 작품 ID")
    title: AnilistTitle | None = None
    type: str | None = Field(None, description="예: ANIME, MANGA")
    format: str | None = Field(None, description="예: TV, MOVIE, OVA, SPECIAL")
    status: str | None = Field(None, description="예: RELEASING, FINISHED, NOT_YET_RELEASED")
    season: str | None = Field(None, description="예: WINTER, SPRING, SUMMER, FALL")
    seasonYear: int | None = None
    episodes: int | None = None
    duration: int | None = Field(None, description="에피당 러닝타임(분) 등 AniList 규칙")
    genres: list[str] = Field(default_factory=list)
    coverImage: AnilistCoverImage | None = None
    bannerImage: str | None = None
    averageScore: int | None = Field(None, description="평균 점수 (0–100)")
    meanScore: int | None = None
    popularity: int | None = None
    trending: int | None = Field(None, description="트렌딩 스코어")
    koreanTitle: str | None = Field(
        None,
        description="TMDB TV (ko-KR) 표제 — 서버에서 보강",
    )

    @field_validator("genres", mode="before")
    @classmethod
    def _genres_strings_only(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [x for x in v if isinstance(x, str)]
        return []


class AnilistPageInfo(BaseModel):
    total: int | None = None
    hasNextPage: bool | None = None


class TrendingAnimePageResponse(BaseModel):
    """AniList Page → 인기순 애니 목록 (/api/v1/anilist/trending-anime, 경로 레거시)"""

    pageInfo: AnilistPageInfo | None = None
    media: list[AnilistMedia] = Field(default_factory=list)


class AnilistMediaDetailResponse(BaseModel):
    """AniList Media 단건 (/api/v1/anilist/media/{id})"""

    id: int
    title: AnilistTitle | None = None
    koreanTitle: str | None = Field(
        None,
        description="TMDB TV (ko-KR) 표제 — 서버에서 보강",
    )
