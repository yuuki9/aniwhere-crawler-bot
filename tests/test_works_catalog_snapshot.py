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
