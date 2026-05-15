# 상점 리빌드 및 `works` 카탈로그 LLM 매핑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CSV 파이프라인이 Gemini 출력으로 상점을 저장할 때 `shop_works`는 **기존 MySQL `works.id`만** 연결하고, 매칭 후보는 **`works` 제목 컬럼으로 만든 카탈로그 스냅샷**을 LLM 컨텍스트로 넣어 추론하며, 카탈로그가 크면 **청크별 호출 후 `work_id` 합집합**으로 합친다.

**Architecture:** (1) 파이프라인 시작 시 DB에서 `works` 행을 읽어 순수 함수 모듈에서 **[{id, titles}]** 형태로 직렬화·청크 분할한다. (2) **청크 0** 호출에서는 기존과 동일한 `rdb` JSON 전체 + `work_ids`를 받고, **추가 청크**에서는 동일 크롤 원문·상점 메타를 넣되 출력은 **`work_ids`만** 요청해 토큰을 줄인다. (3) 모든 ID는 **`allowed_ids`** 집합으로 서버 측 필터한다. (4) `save_shop_to_db` / `update_shop_in_db`는 문자열 `works`로 `works` 행을 만들지 않고 **`work_ids`만** `shop_works`에 `INSERT IGNORE`한다.

**Tech Stack:** Python 3.11+, FastAPI 프로젝트(`app/`), `google-genai`, `aiomysql`, `pytest`.

---

## 파일 구조 (이 계획이 만지는 것)

| 파일 | 역할 |
|------|------|
| `requirements.txt` | `pytest` 의존성 추가 |
| `app/core/config.py` | 카탈로그 청크 최대 문자 수 설정 필드 추가 |
| `app/services/works_catalog_snapshot.py` | 카탈로그 행 정규화·직렬화·청크·ID 병합·필터 (신규, 순수 함수 중심) |
| `app/services/db_service.py` | `fetch_works_catalog_rows`, `save_shop_to_db` / `update_shop_in_db`의 작품 연결 방식 변경 |
| `app/services/refine_service.py` | 카탈로그 청크를 받아 다중 Gemini 호출·결과 병합 (`refine_shop_with_catalog`) |
| `run_pipeline.py` | MySQL 사용 시 풀에서 `works` 목록 로드 후 refine에 전달 |
| `tests/test_works_catalog_snapshot.py` | 스냅샷·청크·필터 단위 테스트 |
| `scripts/sql/truncate_shops_for_rebuild.sql` | 리빌드용 상점 쪽 테이블 TRUNCATE 순서 (선택 실행, **운영 시 FK 순서 확인**) |

---

### Task 1: 테스트 러너 추가

**Files:**

- Modify: `requirements.txt`
- Create: `tests/__init__.py` (빈 파일)

- [ ] **Step 1: `requirements.txt`에 pytest 추가**

파일 끝에 다음 줄을 추가한다.

```text
pytest>=8.0.0
```

- [ ] **Step 2: 빈 패키지 파일 생성**

Create `tests/__init__.py`:

```python
# 테스트 패키지 마커
```

- [ ] **Step 3: 설치 확인**

Run:

```powershell
pip install -r requirements.txt
pytest --version
```

Expected: `pytest` 버전 문자열 출력, 종료 코드 `0`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/__init__.py
git commit -m "chore(test): pytest 의존성 및 tests 패키지 추가"
```

---

### Task 2: 카탈로그 스냅샷 순수 로직

**Files:**

- Create: `app/services/works_catalog_snapshot.py`

- [ ] **Step 1: 신규 파일 전체 작성**

Create `app/services/works_catalog_snapshot.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass

# DB `works` 매칭용 제목 컬럼(스펙과 동일 계열)
TITLE_FIELDS: tuple[str, ...] = (
    "name",
    "korean_title",
    "title_romaji",
    "title_english",
    "title_native",
)


@dataclass(frozen=True)
class CatalogWorkLine:
    """LLM에 넣는 최소 단위: 작품 ID와 사람이 읽을 제목 후보들."""

    id: int
    titles: tuple[str, ...]


def row_dict_to_catalog_line(row: dict) -> CatalogWorkLine | None:
    """MySQL 행 dict → CatalogWorkLine. 표시할 제목이 하나도 없으면 None."""
    raw_id = row.get("id")
    if raw_id is None:
        return None
    try:
        wid = int(raw_id)
    except (TypeError, ValueError):
        return None
    titles: list[str] = []
    for key in TITLE_FIELDS:
        val = row.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            titles.append(s)
    if not titles:
        return None
    return CatalogWorkLine(id=wid, titles=tuple(titles))


def catalog_lines_to_json_blob(lines: list[CatalogWorkLine]) -> str:
    payload = [{"id": ln.id, "titles": list(ln.titles)} for ln in lines]
    return json.dumps(payload, ensure_ascii=False)


def chunk_catalog_lines(
    lines: list[CatalogWorkLine],
    max_chars: int,
) -> list[list[CatalogWorkLine]]:
    """직렬화 길이 기준으로 블록을 나눈다. 단일 행이 한도를 넘으면 단독 청크."""
    if not lines:
        return []
    if max_chars <= 0:
        return [lines]

    chunks: list[list[CatalogWorkLine]] = []
    current: list[CatalogWorkLine] = []

    def serialized(chunk: list[CatalogWorkLine]) -> str:
        return catalog_lines_to_json_blob(chunk)

    for ln in lines:
        trial = current + [ln]
        text = serialized(trial)
        if len(text) <= max_chars:
            current = trial
            continue
        if current:
            chunks.append(current)
            current = []
        single = serialized([ln])
        if len(single) > max_chars:
            chunks.append([ln])
        else:
            current = [ln]

    if current:
        chunks.append(current)
    return chunks


def merge_work_id_lists(chunk_lists: list[list[int]]) -> list[int]:
    """청크별 work_id 목록의 합집합을 첫 등장 순서로 정렬."""
    seen: set[int] = set()
    out: list[int] = []
    for lst in chunk_lists:
        for x in lst:
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out


def filter_work_ids(ids: object, allowed: set[int]) -> list[int]:
    """LLM 출력에서 정수만 골라 허용 집합으로 제한. 순서 유지."""
    if not isinstance(ids, list):
        return []
    out: list[int] = []
    for item in ids:
        try:
            w = int(item)
        except (TypeError, ValueError):
            continue
        if w in allowed:
            out.append(w)
    return out


def allowed_ids_from_lines(lines: list[CatalogWorkLine]) -> set[int]:
    return {ln.id for ln in lines}
```

- [ ] **Step 2: Commit**

```bash
git add app/services/works_catalog_snapshot.py
git commit -m "feat(pipeline): works 카탈로그 스냅샷·청크 순수 로직 추가"
```

---

### Task 3: 스냅샷 단위 테스트 (TDD 완료 확인)

**Files:**

- Create: `tests/test_works_catalog_snapshot.py`

- [ ] **Step 1: 테스트 파일 작성**

Create `tests/test_works_catalog_snapshot.py`:

```python
from app.services.works_catalog_snapshot import (
    CatalogWorkLine,
    allowed_ids_from_lines,
    catalog_lines_to_json_blob,
    chunk_catalog_lines,
    filter_work_ids,
    merge_work_id_lists,
    row_dict_to_catalog_line,
)


def test_row_dict_skips_empty_titles():
    assert row_dict_to_catalog_line({"id": 1}) is None


def test_row_dict_collects_title_fields():
    line = row_dict_to_catalog_line(
        {
            "id": 5,
            "name": " Alpha ",
            "korean_title": None,
            "title_romaji": "Beta",
            "title_english": "",
            "title_native": "  ",
        }
    )
    assert line == CatalogWorkLine(id=5, titles=("Alpha", "Beta"))


def test_chunk_splits_by_length():
    lines = [
        CatalogWorkLine(id=i, titles=(f"Title-{i}",))
        for i in range(1, 6)
    ]
    chunks = chunk_catalog_lines(lines, max_chars=80)
    assert len(chunks) >= 2
    joined = [ln for ch in chunks for ln in ch]
    assert [ln.id for ln in joined] == [ln.id for ln in lines]


def test_merge_and_filter():
    merged = merge_work_id_lists([[1, 2], [2, 3]])
    assert merged == [1, 2, 3]
    allowed = {1, 3}
    assert filter_work_ids([1, 2, 3, "bad", 3.7], allowed) == [1, 3]


def test_allowed_ids_from_lines():
    lines = [CatalogWorkLine(1, ("A",)), CatalogWorkLine(2, ("B",))]
    assert allowed_ids_from_lines(lines) == {1, 2}
```

- [ ] **Step 2: 테스트 실행**

Run:

```powershell
pytest tests/test_works_catalog_snapshot.py -v
```

Expected: 전부 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_works_catalog_snapshot.py
git commit -m "test(pipeline): works 카탈로그 스냅샷 단위 테스트 추가"
```

---

### Task 4: 설정 및 DB에서 카탈로그 로드

**Files:**

- Modify: `app/core/config.py`
- Modify: `app/services/db_service.py`

- [ ] **Step 1: 설정 필드 추가**

`Settings` 클래스에 다음 필드를 추가한다 (`pipeline_sleep_sec` 근처가 적당하다).

```python
    # Gemini refine — works 카탈로그 청크 (대략적 문자 수 한도, JSON 직렬화 기준)
    refine_catalog_chunk_max_chars: int = 120_000
```

- [ ] **Step 2: `db_service.py`에 조회 함수 추가**

`get_db_pool` 아래 등 적당한 위치에 다음 비동기 함수를 추가한다.

```python
async def fetch_works_catalog_rows(pool: aiomysql.Pool) -> list[dict]:
    """
    `works` 전행에서 카탈로그 매칭에 쓸 제목 컬럼만 가져온다.
    행 순서: id 오름차순 (청크 분할 안정화).
    """
    sql = """
        SELECT id, name, korean_title, title_romaji, title_english, title_native
        FROM works
        ORDER BY id ASC
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql)
            col_names = [d[0] for d in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(col_names, tup)) for tup in rows]
```

- [ ] **Step 3: 상점 저장 시 `work_ids`만 연결**

`_ensure_work_id`를 호출하는 두 군데(`save_shop_to_db`, `update_shop_in_db`)에서 작품 처리 루프를 **아래 로직으로 교체**한다.

```python
            work_ids = rdb_data.get("work_ids") or []
            for raw in work_ids:
                try:
                    wid = int(raw)
                except (TypeError, ValueError):
                    continue
                await cur.execute(
                    "INSERT IGNORE INTO shop_works (shop_id, work_id) VALUES (%s, %s)",
                    (shop_id, wid),
                )
```

동시에 로그의 `works=`는 `work_ids` 길이를 찍도록 바꾼다.

```python
        len(rdb_data.get("work_ids") or []),
```

- [ ] **Step 4: Commit**

```bash
git add app/core/config.py app/services/db_service.py
git commit -m "feat(db): works 카탈로그 조회 및 shop_works를 work_ids 기준으로 저장"
```

---

### Task 5: Refine 프롬프트 — 카탈로그 청크 다중 호출

**Files:**

- Modify: `app/services/refine_service.py`

- [ ] **Step 1: 프롬프트 상수 분리 및 필드 변경**

기존 `_PROMPT_TEMPLATE`의 `rdb` 예시에서 **`"works": [...]` 배열을 제거**하고 **`"work_ids": []`** 를 넣는다. 지침 문구도 “작품명 문자열 배열” 대신 **“아래 카탈로그에 나온 id만 `work_ids`에 넣는다. 확신 없으면 생략”** 으로 바꾼다.

예시 블록:

```json
    "work_ids": [101, 205],
```

- [ ] **Step 2: `refine_shop_with_catalog` 추가**

시그니처 예시:

```python
async def refine_shop_with_catalog(
    shop: ShopRecord,
    crawl_text: str,
    catalog_chunks: list[list[CatalogWorkLine]],
    *,
    allowed_work_ids: set[int],
) -> dict:
```

동작:

1. `catalog_chunks`가 비었으면 카탈로그 없이 기존 `refine_shop`과 동일 프롬프트로 1회 호출하되 `work_ids`는 빈 배열 기대.
2. 청크가 있으면:
   - **인덱스 0**: 전체 `_PROMPT_TEMPLATE` + `"카탈로그(청크 1/N): "` + `catalog_lines_to_json_blob(chunk0)` 을 붙여 Gemini 호출 → `base = 파싱 결과`.
   - **인덱스 k>0**: 짧은 보조 프롬프트(상점명·주소·크롤 원문 동일 포함) + 해당 청크 JSON만 → 응답 JSON에서 **`work_ids`만** 추출. 나머지 키는 무시.
3. 각 응답의 `work_ids`는 `filter_work_ids(..., allowed_work_ids)` 통과시킨다.
4. `merge_work_id_lists`로 합친 목록을 `base["rdb"]["work_ids"]`에 넣어 반환한다. `base["rdb"]`가 None이면 그대로 반환.

보조 프롬프트 예시(계획용 초안 — 구현 시 영문 혼합 가능):

```text
동일 상점·동일 블로그 원문이다. 아래 작품 카탈로그(JSON)에 있는 id만 골라 블로그에서 실제 취급·언급된 작품에 해당하는 id를 work_ids 배열로만 출력하라.
카탈로그:
{chunk_json}
출력: 순수 JSON 하나만 — {"work_ids": [정수,...]}
```

공통: `temperature=0.1`, `max_output_tokens`는 보조 호출은 `2048` 정도로 줄여도 된다.

- [ ] **Step 3: Commit**

```bash
git add app/services/refine_service.py
git commit -m "feat(refine): works 카탈로그 청크 기반 다중 Gemini 호출 및 work_ids 병합"
```

---

### Task 6: 파이프라인 연동

**Files:**

- Modify: `run_pipeline.py`

- [ ] **Step 1: import 추가**

```python
from app.services.works_catalog_snapshot import (
    allowed_ids_from_lines,
    chunk_catalog_lines,
    row_dict_to_catalog_line,
)
from app.services.db_service import fetch_works_catalog_rows
from app.services.refine_service import refine_shop_with_catalog
```

(`fetch_works_catalog_rows`는 기존 `db_service` import 목록에 합친다.)

- [ ] **Step 2: `run_pipeline_async`에서 카탈로그 선로드**

`get_db_pool()` 이후, `do_mysql`이 True일 때 한 번만:

```python
    catalog_lines = []
    allowed_work_ids: set[int] = set()
    catalog_chunks: list[list] = []
    if do_mysql:
        raw_rows = await fetch_works_catalog_rows(pool)
        catalog_lines = [ln for ln in (row_dict_to_catalog_line(r) for r in raw_rows) if ln is not None]
        allowed_work_ids = allowed_ids_from_lines(catalog_lines)
        max_chars = settings.refine_catalog_chunk_max_chars
        catalog_chunks = chunk_catalog_lines(catalog_lines, max_chars)
```

- [ ] **Step 3: `_process_one_shop` 시그니처·본문**

`_process_one_shop`에 `catalog_chunks`, `allowed_work_ids` 인자를 추가하고, refine 호출을 다음으로 교체한다.

```python
    result = await refine_shop_with_catalog(
        shop,
        crawl_text,
        catalog_chunks,
        allowed_work_ids=allowed_work_ids,
    )
```

`run_pipeline_async`에서 `_process_one_shop(...)` 호출부에 위 두 인자를 넘긴다.

- [ ] **Step 4: 수동 검증 (로컬)**

MySQL·Gemini 키가 있는 환경에서:

```powershell
python run_pipeline.py --no-collect --mysql --chroma --limit 1 --input data/shop_with_blogs.csv
```

Expected: 오류 없이 완료, 로그에 refine 단계 표시, DB에 `shop_works.work_id`가 **기존 works.id**만 참조.

- [ ] **Step 5: Commit**

```bash
git add run_pipeline.py
git commit -m "feat(pipeline): run_pipeline에 works 카탈로그 선로드 및 refine_shop_with_catalog 연동"
```

---

### Task 7: 리빌드용 SQL 스크립트 (운영 가이드)

**Files:**

- Create: `scripts/sql/truncate_shops_for_rebuild.sql`

- [ ] **Step 1: SQL 작성**

Create `scripts/sql/truncate_shops_for_rebuild.sql`:

```sql
-- 상점 데이터만 재구축할 때 참고용. FK 제약에 맞게 순서 조정 필요할 수 있음.
-- 실행 전 백업 필수. works 테이블은 건드리지 않는다.

SET FOREIGN_KEY_CHECKS = 0;

TRUNCATE TABLE shop_works;
TRUNCATE TABLE shop_categories;
TRUNCATE TABLE shop_links;
TRUNCATE TABLE shop_details;
TRUNCATE TABLE shops;

SET FOREIGN_KEY_CHECKS = 1;
```

주석으로 **실제 스키마에 `regions` 등 다른 FK가 있으면 저장소의 `aniwhere_schema.sql`과 대조하라**고 적는다.

- [ ] **Step 2: Commit**

```bash
git add scripts/sql/truncate_shops_for_rebuild.sql
git commit -m "chore(sql): 상점 리빌드용 TRUNCATE 참고 스크립트 추가"
```

---

## Spec coverage (self-review)

| 스펙 요구 | 이 계획 Task |
|-----------|----------------|
| CSV 파이프라인 유지 | Task 6 (`run_pipeline`) |
| 기존 `works` 유지·수동 | Task 4 조회만, INSERT works 없음 |
| `work_id`만 연결·실패 생략 | Task 4·5 (`work_ids` + 필터) |
| 제목 컬럼만 별칭 | Task 2 `TITLE_FIELDS` |
| 카탈로그 전체·초과 시 청크 | Task 2·5·6 |
| 청크 합집합 | Task 2 `merge_work_id_lists` + Task 5 |
| 서버 검증 | Task 2 `filter_work_ids` + Task 5 |

## Placeholder scan

- 위 단계에 `TBD`/`implement later` 없음. 스키마 FK 차이는 Task 7 주석으로 명시.

## Type / 이름 일관성

- JSON 필드명 **`work_ids`**, DB 컬럼 **`work_id`**, 파이썬 **`allowed_work_ids`**, **`CatalogWorkLine.id`** 로 통일.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-15-shop-rebuild-works-llm-mapping-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 태스크마다 새 서브에이전트를 붙이고 태스크 사이에 리뷰

**2. Inline Execution** — 이 세션에서 순차 구현·중간 확인

**Which approach?**
