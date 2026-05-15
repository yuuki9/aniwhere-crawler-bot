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
        if isinstance(item, bool):
            continue
        if not isinstance(item, int):
            continue
        if item in allowed:
            out.append(item)
    return out


def allowed_ids_from_lines(lines: list[CatalogWorkLine]) -> set[int]:
    return {ln.id for ln in lines}
