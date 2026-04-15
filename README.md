# Aniwhere Crawler Bot

피규어·가챠·애니 굿즈 샵 데이터를 **CSV → 블로그 수집 → 크롤링 → Gemini 정제 → MySQL + ChromaDB**까지 한 번에 처리하고, FastAPI로 **RAG 검색**을 제공하는 프로젝트입니다.

---

## 전체 데이터 파이프라인 (권장)

로컬에서 아래 한 줄이 **1~4단계 전체**를 순서대로 수행합니다.

```bash
python run_pipeline.py
```

### 단계별로 무엇을 하나요?

| 단계 | 설명 |
|------|------|
| **1. 블로그 URL 보강** | `data/shop.csv`(주소·상점명·좌표)를 읽고, **네이버 블로그 검색 API**로 상점명 기준 블로그 링크를 모아 `data/shop_with_blogs.csv`에 저장합니다. |
| **2. 크롤링** | 각 상점의 블로그 URL(기본 상위 5개)을 HTTP로 받아 본문·메타 텍스트를 뽑습니다. (`app/services/blog_crawl_service.py`) |
| **3. 정제 (refine)** | 크롤 원문 + 상점 메타를 **Gemini**에 넘겨, RDB용 JSON(`rdb`)과 검색용 자연어(`knowledge_base_text`)를 생성합니다. (`app/services/refine_service.py`) |
| **4. 저장** | **`rdb` → MySQL** (`app/services/db_service.py`의 `save_shop_to_db`), **`knowledge_base_text` → ChromaDB** 임베딩 upsert (`app/services/chroma_ingest_service.py`). 동시에 `{OUTPUT_DIR}/knowledge_base/{상점명}.txt`에 텍스트 백업을 남깁니다. |

- **이미 `shop_with_blogs.csv`가 있으면** 네이버 호출을 건너뛰고 싶을 때:

  ```bash
  python run_pipeline.py --no-collect
  ```

  이 경우 기본 입력 파일은 `data/shop_with_blogs.csv`입니다. (`--input`으로 경로 지정 가능)

- **MySQL만 / Chroma만 조절:**

  ```bash
  python run_pipeline.py --no-chroma
  python run_pipeline.py --no-mysql --no-chroma   # 정제·로컬 txt만 (DB 미저장)
  ```

  Chroma upsert는 **MySQL에 저장된 `shop_id`**를 id로 쓰므로, **Chroma만 켜고 MySQL을 끄는 구성은 지원하지 않습니다.**

- **상점 간 대기·크롤 링크 수:** `.env`의 `PIPELINE_SLEEP_SEC`, `PIPELINE_MAX_BLOG_LINKS_CRAWL` 또는 CLI `--sleep`, `--max-blog-links`.

---

## 입력 CSV 형식

### `data/shop.csv` (블로그 수집 전)

| 컬럼 | 필수 | 설명 |
|------|------|------|
| address | ✓ | 주소 |
| name | ✓ | 상점명 |
| px | ✓ | 경도 |
| py | ✓ | 위도 |

### `data/shop_with_blogs.csv` (수집 후)

위 컬럼에 더해 **`blog`** 컬럼에 네이버 블로그 URL이 **쉼표로 구분**되어 들어갑니다. (`app/services/naver_search_service.py`가 저장)

---

## 환경 변수

`.env.example`을 복사해 `.env`를 만든 뒤 값을 채웁니다.

**파이프라인에 필요한 최소 항목:**

- `GEMINI_API_KEY` — 정제 및 RAG 답변
- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` — `--no-collect`를 쓰지 않는 경우(블로그 URL 자동 수집)
- `MYSQL_*` — MySQL 저장을 켤 때 (`--no-mysql`이 아닐 때)

**검색·벡터 저장:**

- `CHROMA_PERSIST_PATH` — Chroma 영속 디렉터리 (기본 `chromadb`). `docker-compose` 볼륨과 맞출 것.
- RAG 임베딩 모델은 코드상 `all-MiniLM-L6-v2` (CPU).

---

## FastAPI 서버 (검색 API)

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

- `GET /health` — 서버 및 Chroma `shops` 컬렉션 상태
- `GET /api/v1/search?q=&n=` — RAG 검색 (분당 10회 제한, 입력 가드레일)

`app/api/shops.py`에 CSV 업로드용 엔드포인트가 정의되어 있으나, **`app/main.py`에는 아직 라우터가 포함되어 있지 않습니다.** 필요 시 `main.py`에 `shops` 라우터를 추가하세요.

Docker:

```bash
docker compose up --build
```

---

## 주요 디렉터리·모듈

```
app/
  main.py                 # FastAPI 앱 (health, search)
  core/config.py          # pydantic-settings
  api/                    # 라우터
  services/
    blog_crawl_service.py # 블로그 크롤
    naver_search_service.py
    refine_service.py     # Gemini 정제
    db_service.py         # MySQL 저장 + shop_exists_by_name
    chroma_ingest_service.py  # Chroma upsert (파이프라인)
    rag_service.py        # 검색 시 Chroma + Gemini
  schemas/shop.py         # ShopRecord
  utils/
    csv_helpers.py        # 업로드용 청크 CSV
    local_csv.py          # 로컬 파일 → ShopRecord
data/
  shop.csv
  shop_with_blogs.csv
run_pipeline.py           # ★ 통합 CLI 파이프라인
embed_to_chromadb.py      # S3의 .txt → Chroma (레거시/보조)
process_shops.py          # 구 스키마용 배치 (아래 참고)
retry_failed.py
init_db.sql               # MySQL 스키마 (save_shop_to_db와 맞춤)
```

---

## 기타 스크립트

| 스크립트 | 설명 |
|----------|------|
| `embed_to_chromadb.py` | S3 `shops/*.txt`를 내려받아 **컬렉션을 삭제 후 재생성**합니다. 로컬 파이프라인으로 Chroma를 채우는 경우와 중복 실행에 주의하세요. |
| `process_shops.py` | **regions / shop_details 등 구 스키마**를 가정한 예전 배치입니다. DB가 `init_db.sql`과 같다면 **`run_pipeline.py` 사용을 권장**합니다. DB 연결은 `get_db_pool()`(`.env`)을 사용합니다. |
| `retry_failed.py` | 실패 상점 이름 목록만 골라 재시도하는 보조 스크립트. |

---

## 라이선스·주의

- 네이버·블로그·Gemini 이용 시 각 서비스 약관 및 호출 한도를 준수하세요.
- 운영 환경에서는 DB 비밀번호 등 민감 정보를 **반드시 `.env`로만** 관리하고 저장소에 커밋하지 마세요.
