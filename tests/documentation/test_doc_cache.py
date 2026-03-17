import pytest

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    DocItem,
    DocItemRef,
    DocItemType,
    EntityQuery,
    FileDoc,
    FileDocType,
)


@pytest.fixture
def doc_cache(tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "doc_cache"),
            start_with_clean_cache=True,
        ),
        project_path=str(tmp_path),
    )
    file_doc = FileDoc(
        path="src/foo.py",
        type=FileDocType.CODE,
        description="A utility module.",
        items=[
            DocItemRef(name="MyClass", type=DocItemType.CLASS),
            DocItemRef(name="get_user", type=DocItemType.METHOD, parent="MyClass"),
            DocItemRef(name="format_name", type=DocItemType.FUNCTION),
            DocItemRef(name="MAX_SIZE", type=DocItemType.CONSTANT),
            DocItemRef(name="parse_data", type=DocItemType.FUNCTION),
        ],
    )
    cache.set_file_documentation("src/foo.py", file_doc)
    # Store entity docs so search_documentation can load them
    for ref in file_doc.items:
        cache.set_entity_documentation(
            "src/foo.py",
            ref,
            DocItem(name=ref.name, type=ref.type, description=f"{ref.name} docs.", parent=ref.parent),
        )
    return cache


# ---------------------------------------------------------------------------
# File-level lookup (queries=None)
# ---------------------------------------------------------------------------


def test_no_queries_returns_all_entities(doc_cache):
    file_doc, items = doc_cache.search_documentation("src/foo.py")
    assert isinstance(file_doc, FileDoc)
    assert len(items) == 5


def test_unknown_file_returns_none(doc_cache):
    file_doc, items = doc_cache.search_documentation("missing.py")
    assert file_doc is None
    assert items == []


# ---------------------------------------------------------------------------
# Exact-match tier
# ---------------------------------------------------------------------------


def test_exact_name_and_type(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="MyClass", type=DocItemType.CLASS)]
    )
    assert len(items) == 1
    assert items[0].name == "MyClass"
    assert items[0].type == DocItemType.CLASS


def test_exact_name_any_type(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="MyClass")]
    )
    assert len(items) == 1
    assert items[0].name == "MyClass"


def test_exact_name_wrong_type_falls_back(doc_cache):
    # Tier 1 (exact + FUNCTION type) misses; falls back to exact name any type
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="MyClass", type=DocItemType.FUNCTION)]
    )
    assert len(items) == 1
    assert items[0].name == "MyClass"


# ---------------------------------------------------------------------------
# Case-insensitive tier
# ---------------------------------------------------------------------------


def test_case_insensitive_match(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="myclass")]
    )
    assert len(items) == 1
    assert items[0].name == "MyClass"


def test_case_insensitive_with_type_preference(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="FORMAT_NAME", type=DocItemType.FUNCTION)]
    )
    assert len(items) == 1
    assert items[0].name == "format_name"
    assert items[0].type == DocItemType.FUNCTION


# ---------------------------------------------------------------------------
# Substring tier
# ---------------------------------------------------------------------------


def test_substring_match(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="parse")]
    )
    assert len(items) == 1
    assert items[0].name == "parse_data"


def test_substring_prefers_correct_type(tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "doc_cache"),
            start_with_clean_cache=True,
        ),
        project_path=str(tmp_path),
    )
    file_doc = FileDoc(
        path="src/bar.py",
        type=FileDocType.CODE,
        description="Bar module.",
        items=[
            DocItemRef(name="parse_helper", type=DocItemType.CLASS),
            DocItemRef(name="parse_data", type=DocItemType.FUNCTION),
        ],
    )
    cache.set_file_documentation("src/bar.py", file_doc)
    for ref in file_doc.items:
        cache.set_entity_documentation(
            "src/bar.py",
            ref,
            DocItem(name=ref.name, type=ref.type, description=f"{ref.name} docs."),
        )

    _, items = cache.search_documentation(
        "src/bar.py", [EntityQuery(name="parse", type=DocItemType.FUNCTION)]
    )
    assert all(i.type == DocItemType.FUNCTION for i in items)
    assert any(i.name == "parse_data" for i in items)


# ---------------------------------------------------------------------------
# Parent filter
# ---------------------------------------------------------------------------


def test_parent_filter(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(parent="MyClass")]
    )
    assert len(items) == 1
    assert items[0].name == "get_user"
    assert items[0].parent == "MyClass"


# ---------------------------------------------------------------------------
# Multiple queries
# ---------------------------------------------------------------------------


def test_multiple_queries(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py",
        [EntityQuery(name="MyClass"), EntityQuery(name="parse_data")],
    )
    assert len(items) == 2
    names = {i.name for i in items}
    assert names == {"MyClass", "parse_data"}


def test_multiple_queries_deduplication(doc_cache):
    _, items = doc_cache.search_documentation(
        "src/foo.py",
        [EntityQuery(name="MyClass"), EntityQuery(name="MyClass")],
    )
    assert len(items) == 1


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------


def test_no_match_returns_empty_list(doc_cache):
    file_doc, items = doc_cache.search_documentation(
        "src/foo.py", [EntityQuery(name="nonexistent")]
    )
    assert isinstance(file_doc, FileDoc)
    assert items == []
