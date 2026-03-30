# Aniwhere AI — 하비숍 요약 API

하비숍 정보가 담긴 CSV를 업로드하면 Google Gemini API가 각 상점의 특징을 요약해 주는 FastAPI 서버입니다.

## 프로젝트 구조

```
aniwhere-ai/
├── app/
│   ├── main.py              # FastAPI 앱 초기화 & 미들웨어
│   ├── api/
│   │   ├── health.py        # GET /health
│   │   └── shops.py         # POST /api/v1/shops/summarize, /parse
│   ├── services/
│   │   ├── csv_service.py   # CSV 파싱 · 검증 오케스트레이터
│   │   └── gemini_service.py# Gemini API 연동 + 프롬프트 빌더
│   ├── schemas/
│   │   ├── shop.py          # ShopRecord (CSV 단일 행 모델)
│   │   └── summary.py       # ShopSummary, SummarizeBatchResponse
│   ├── core/
│   │   ├── config.py        # pydantic-settings 기반 환경 설정
│   │   └── exceptions.py    # 커스텀 HTTPException 정의
│   └── utils/
│       └── csv_helpers.py   # 청크 이터레이터, 링크 파서 등 순수 유틸
├── data/
│   └── samples/
│       └── sample.csv       # 테스트용 샘플 데이터
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## 빠른 시작

### 1. 환경 설정

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. `.env` 파일 생성

```bash
cp .env.example .env
# GEMINI_API_KEY 값을 실제 키로 교체
```

### 3. 서버 실행

```bash
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs

## 주요 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |
| POST | `/api/v1/shops/summarize` | CSV 업로드 → Gemini 요약 반환 |
| POST | `/api/v1/shops/parse` | CSV 파싱 결과만 반환 (디버그용) |

## CSV 포맷

| 컬럼 | 타입 | 설명 |
|------|------|------|
| address | str | 상점 주소 |
| name | str | 상점명 |
| px | float | 경도 |
| py | float | 위도 |
| blog | str | 네이버 블로그 링크 (콤마로 구분, 복수 가능) |
| insta | str | 인스타그램 URL |
| x | str | X(트위터) URL |
| place | str | 네이버 플레이스 URL |
| homepage | str | 홈페이지 URL |

## 대용량 CSV 처리

`app/utils/csv_helpers.py`의 `iter_csv_batches()`가 pandas `chunksize`를 활용해
배치 단위로 읽습니다. 기본값은 `.env`의 `CSV_BATCH_SIZE`(기본 100행)로 조절 가능합니다.

## Gemini 프롬프트 수정

`app/services/gemini_service.py`의 `_build_prompt()` 함수에서 역할 지정, 출력 형식,
Few-shot 예시 등 프롬프트 엔지니어링 작업을 수행합니다.
