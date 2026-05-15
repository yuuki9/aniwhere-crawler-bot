# Design: `works` 테이블 AniList 카탈로그 연동

## 목적

AniList API 응답을 기반으로 MySQL의 **`works`** 행을 마스터 카탈로그처럼 유지한다. 기존 상점 파이프라인(`shop_works`)과 호환되며, AniList와 아직 매칭되지 않은 작품은 `anilist_id` 없이 존재할 수 있다.

## 합의된 결정

| 항목 | 결정 |
|------|------|
| 데이터 목적 | AniList 기준 작품 마스터 + 상점 작품과 동일 축 |
| 스키마 전략 | `works` 행 확장 (별도 AniList 전용 테이블 없음) |
| `anilist_id` | NULL 허용; 값이 있으면 유일(UNIQUE) |
| 장르 | JSON 배열(문자열) 컬럼 |
| TMDB 보강 | `korean_title`, `tmdb_logo_url` 저장 (핵심 UX) |
| 배너 | 저장하지 않음 |
| 인기 지표 | `popularity` 컬럼 유지 |
| 제목 | 언어별 컬럼으로 저장 (JSON 묶음 아님) |

## 컬럼 정의 (추가·의미)

기존 `works`의 PK·`name`은 유지한다. 아래는 **신규 또는 명시적으로 쓰는 필드**이다.

| 컬럼 | 타입(권장) | 설명 |
|------|------------|------|
| `anilist_id` | `INT UNSIGNED NULL` | AniList `Media.id`. NULL 허용. NOT NULL 값은 테이블 내 유일. |
| `title_romaji` | `VARCHAR(512) NULL` | AniList `title.romaji` |
| `title_english` | `VARCHAR(512) NULL` | AniList `title.english` |
| `title_native` | `VARCHAR(512) NULL` | AniList `title.native` |
| `korean_title` | `VARCHAR(512) NULL` | TMDB 보강 한글 표제 (API의 `koreanTitle`) |
| `genres` | `JSON NULL` | 장르 문자열 배열 |
| `cover_url` | `VARCHAR(1024) NULL` | 대표 커버 이미지 URL 하나 (예: `coverImage.extraLarge`) |
| `tmdb_logo_url` | `VARCHAR(1024) NULL` | TMDB 로고 절대 URL |
| `popularity` | `INT NULL` | AniList `popularity` |
| `anilist_synced_at` | `DATETIME(6) NULL` | AniList(+TMDB 보강) 경로로 성공 upsert한 시각 |

의도적으로 두지 않는 필드: `bannerImage`, `idMal`, `format`, `status`, `season`, `seasonYear`, `episodes`, `duration`, `averageScore`, `meanScore`, `trending`, 커버 해상도별 중복·색상 필드.

향후 필터·정렬 요구가 생기면 해당 필드만 단계적으로 추가한다.

## 인덱스

- `UNIQUE KEY uk_works_anilist_id (anilist_id)` — 동일 AniList 작품 중복 행 방지.
- 검색 패턴이 정해지면 `korean_title`, `title_romaji` 등에 대한 보조 인덱스는 별도 검토.

## `name` 필드 규칙

- 상점 전용으로만 생성되는 행: 기존과 같이 `name`만 채워도 된다 (`anilist_id` NULL 가능).
- AniList 동기화로 채우거나 갱신할 때: 표시용으로 `name`을 예를 들어 `COALESCE(korean_title, title_romaji, title_english, title_native)` 순으로 설정한다. 운영 우선순위는 구현 시 한 곳에서 상수화한다.

## 동기화(upsert) 동작

- 키: `anilist_id`가 있는 경우 해당 값으로 식별한다.
- AniList 목록/단건 등 ingest 소스에서 받은 스칼라·JSON·URL·`popularity`를 위 컬럼에 맞춰 **덮어쓴다**.
- TMDB가 비활성이거나 매칭 실패 시 `korean_title`·`tmdb_logo_url`은 NULL로 둘 수 있다.
- `anilist_synced_at`은 ingest 성공 시마다 갱신한다 (AniList 본문만 성공한 경우에도 갱신할지 여부는 구현에서 일관되게 정하면 된다).

## 레거시·매칭

- `name` 기반 기존 행과 AniList 행의 병합·중복 제거는 별도 매칭 프로세스로 다루며 본 스펙 범위 밖이다.

## 테스트·검증 (구현 시)

- 마이그레이션 적용 후 `anilist_id` UNIQUE 및 NULL 다건 허용 동작 확인.
- ingest 한 건에 대해 컬럼 매핑이 현재 API 스키마(`AnilistMedia`)와 일치하는지 확인.
