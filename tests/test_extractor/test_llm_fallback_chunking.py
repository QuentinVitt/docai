from __future__ import annotations

import pytest

from docai.extractor.datatypes import Entity, EntityCategory
from docai.extractor.llm_fallback import EntityList, _build_chunks, _merge_entities

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(name: str, category: EntityCategory = EntityCategory.callable, **kwargs) -> Entity:
    return Entity(
        name=name,
        category=category,
        kind=kwargs.get("kind", "function"),
        parent=kwargs.get("parent", None),
        signature=kwargs.get("signature", None),
    )


# ---------------------------------------------------------------------------
# _build_chunks
# ---------------------------------------------------------------------------


class TestBuildChunksNoChunking:
    """Files at or below chunk_size return a single element with full content."""

    @pytest.mark.unit
    def test_file_exactly_at_chunk_size_returns_single_element(self) -> None:
        lines = [f"line{i}" for i in range(10)]
        result = _build_chunks(lines, chunk_size=10, header_size=3, overlap=2)
        assert len(result) == 1
        assert result[0] == "\n".join(lines)

    @pytest.mark.unit
    def test_file_below_chunk_size_returns_single_element(self) -> None:
        lines = [f"line{i}" for i in range(5)]
        result = _build_chunks(lines, chunk_size=10, header_size=3, overlap=2)
        assert len(result) == 1
        assert result[0] == "\n".join(lines)

    @pytest.mark.unit
    def test_empty_lines_returns_single_element_with_empty_string(self) -> None:
        result = _build_chunks([], chunk_size=10, header_size=3, overlap=2)
        assert len(result) == 1
        assert result[0] == ""

    @pytest.mark.unit
    def test_no_separator_injected_when_no_chunking(self) -> None:
        lines = ["a", "b", "c"]
        result = _build_chunks(lines, chunk_size=10, header_size=3, overlap=2)
        assert "# ..." not in result[0]


class TestBuildChunksChunking:
    """Files above chunk_size are split with header prepended to each chunk."""

    @pytest.mark.unit
    def test_remaining_fits_in_one_body_returns_single_chunk(self) -> None:
        # chunk_size=5, header_size=2, overlap=1
        # lines = 6 > 5 → chunked; header=lines[:2], remaining=lines[2:6] (4 lines < chunk_size=5)
        lines = ["h0", "h1", "b0", "b1", "b2", "b3"]
        result = _build_chunks(lines, chunk_size=5, header_size=2, overlap=1)
        assert len(result) == 1

    @pytest.mark.unit
    def test_multiple_bodies_produces_correct_chunk_count(self) -> None:
        # chunk_size=4, header_size=2, overlap=1, step=3
        # lines = 9 > 4 → chunked; header=lines[:2], remaining=lines[2:9] (7 lines)
        # range(0, 7, 3) → [0, 3, 6] → 3 chunks
        lines = [f"line{i}" for i in range(9)]
        result = _build_chunks(lines, chunk_size=4, header_size=2, overlap=1)
        assert len(result) == 3

    @pytest.mark.unit
    def test_every_chunk_starts_with_header_lines(self) -> None:
        lines = ["h0", "h1", "b0", "b1", "b2", "b3", "b4", "b5", "b6"]
        result = _build_chunks(lines, chunk_size=4, header_size=2, overlap=1)
        header_prefix = "h0\nh1"
        for chunk in result:
            assert chunk.startswith(header_prefix)

    @pytest.mark.unit
    def test_separator_appears_between_header_and_body(self) -> None:
        lines = ["h0", "h1", "b0", "b1", "b2", "b3", "b4", "b5", "b6"]
        result = _build_chunks(lines, chunk_size=4, header_size=2, overlap=1)
        for chunk in result:
            assert "\n# ...\n" in chunk

    @pytest.mark.unit
    def test_consecutive_chunks_overlap_by_overlap_lines(self) -> None:
        # chunk_size=4, header_size=2, overlap=1, step=3
        # remaining = [b0..b6]; chunk1 body = [b0,b1,b2,b3], chunk2 body = [b3,b4,b5,b6]
        # overlap: b3 appears in both
        lines = ["h0", "h1", "b0", "b1", "b2", "b3", "b4", "b5", "b6"]
        result = _build_chunks(lines, chunk_size=4, header_size=2, overlap=1)
        assert len(result) >= 2
        # Last line of chunk 1 body == first line of chunk 2 body
        body1 = result[0].split("\n# ...\n")[1]
        body2 = result[1].split("\n# ...\n")[1]
        last_of_body1 = body1.split("\n")[-1]
        first_of_body2 = body2.split("\n")[0]
        assert last_of_body1 == first_of_body2

    @pytest.mark.unit
    def test_last_chunk_includes_all_remaining_lines(self) -> None:
        # chunk_size=4, header_size=2, overlap=1
        # remaining = [b0..b6]; last chunk body starts at index 6 → [b6]
        lines = ["h0", "h1", "b0", "b1", "b2", "b3", "b4", "b5", "b6"]
        result = _build_chunks(lines, chunk_size=4, header_size=2, overlap=1)
        last_body = result[-1].split("\n# ...\n")[1]
        assert "b6" in last_body


# ---------------------------------------------------------------------------
# _merge_entities
# ---------------------------------------------------------------------------


class TestMergeEntities:

    @pytest.mark.unit
    def test_single_list_returned_unchanged(self) -> None:
        e = _entity("foo")
        result = _merge_entities(EntityList(entities=[e]))
        assert result.entities == [e]

    @pytest.mark.unit
    def test_two_lists_no_duplicates_returns_all(self) -> None:
        e1 = _entity("foo", EntityCategory.callable)
        e2 = _entity("bar", EntityCategory.type)
        result = _merge_entities(
            EntityList(entities=[e1]),
            EntityList(entities=[e2]),
        )
        assert result.entities == [e1, e2]

    @pytest.mark.unit
    def test_duplicate_name_and_category_keeps_first(self) -> None:
        e1 = _entity("foo", EntityCategory.callable, signature="def foo():")
        e2 = _entity("foo", EntityCategory.callable, signature="def foo(self):")
        result = _merge_entities(
            EntityList(entities=[e1]),
            EntityList(entities=[e2]),
        )
        assert len(result.entities) == 1
        assert result.entities[0].signature == "def foo():"

    @pytest.mark.unit
    def test_same_name_different_category_both_kept(self) -> None:
        e1 = _entity("foo", EntityCategory.callable)
        e2 = _entity("foo", EntityCategory.type)
        result = _merge_entities(
            EntityList(entities=[e1]),
            EntityList(entities=[e2]),
        )
        assert len(result.entities) == 2

    @pytest.mark.unit
    def test_empty_lists_returns_empty_entity_list(self) -> None:
        result = _merge_entities(
            EntityList(entities=[]),
            EntityList(entities=[]),
        )
        assert result.entities == []

    @pytest.mark.unit
    def test_multiple_lists_mixed_duplicates_first_seen_wins_order_preserved(self) -> None:
        e_a = _entity("a", EntityCategory.callable)
        e_b = _entity("b", EntityCategory.type)
        e_a_dup = _entity("a", EntityCategory.callable, signature="duplicate")
        e_c = _entity("c", EntityCategory.variable)
        result = _merge_entities(
            EntityList(entities=[e_a, e_b]),
            EntityList(entities=[e_a_dup, e_c]),
        )
        assert [e.name for e in result.entities] == ["a", "b", "c"]
        assert result.entities[0].signature is None  # first occurrence wins, not duplicate
