import pytest

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    DocItem,
    DocItemType,
    FileDoc,
    FileDocType,
    DocumentationCacheConfig,
)


@pytest.fixture
def doc_cache(tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "doc_cache"),
            start_with_clean_cache=True,
        )
    )
    file_doc = FileDoc(
        path="src/foo.py",
        type=FileDocType.CODE,
        description="A utility module.",
        items=[
            DocItem(name="MyClass", type=DocItemType.CLASS, description="A class."),
            DocItem(
                name="get_user",
                type=DocItemType.METHOD,
                description="Gets a user.",
                parent="MyClass",
            ),
            DocItem(
                name="format_name",
                type=DocItemType.FUNCTION,
                description="Formats a name.",
            ),
            DocItem(
                name="MAX_SIZE",
                type=DocItemType.CONSTANT,
                description="Max size constant.",
            ),
            DocItem(
                name="parse_data",
                type=DocItemType.FUNCTION,
                description="Parses data.",
            ),
        ],
    )
    cache.set_file_documentation("src/foo.py", file_doc)
    return cache


# ---------------------------------------------------------------------------
# File-level lookup (entity_name=None)
# ---------------------------------------------------------------------------


def test_no_entity_name_returns_file_doc_and_empty_list(doc_cache):
    file_doc, items = doc_cache.search_documentation("src/foo.py")
    assert isinstance(file_doc, FileDoc)
    assert items == []


def test_unknown_file_returns_none(doc_cache):
    file_doc, items = doc_cache.search_documentation("missing.py")
    assert file_doc is None
    assert items == []


# ---------------------------------------------------------------------------
# Exact-match tier
# ---------------------------------------------------------------------------


def test_exact_name_and_type(doc_cache):
    _, items = doc_cache.search_documentation("src/foo.py", "MyClass", DocItemType.CLASS)
    assert len(items) == 1
    assert items[0].name == "MyClass"
    assert items[0].type == DocItemType.CLASS


def test_exact_name_any_type(doc_cache):
    _, items = doc_cache.search_documentation("src/foo.py", "MyClass")
    assert len(items) == 1
    assert items[0].name == "MyClass"


def test_exact_name_wrong_type_falls_back(doc_cache):
    # Tier 1 (exact + FUNCTION type) misses; tier 2 (exact name, any type) matches
    _, items = doc_cache.search_documentation(
        "src/foo.py", "MyClass", DocItemType.FUNCTION
    )
    assert len(items) == 1
    assert items[0].name == "MyClass"


# ---------------------------------------------------------------------------
# Case-insensitive tier
# ---------------------------------------------------------------------------


def test_case_insensitive_match(doc_cache):
    _, items = doc_cache.search_documentation("src/foo.py", "myclass")
    assert len(items) == 1
    assert items[0].name == "MyClass"


def test_case_insensitive_with_type_preference(doc_cache):
    # "format_name" exists as FUNCTION; query with FUNCTION type should return it
    _, items = doc_cache.search_documentation(
        "src/foo.py", "FORMAT_NAME", DocItemType.FUNCTION
    )
    assert len(items) == 1
    assert items[0].name == "format_name"
    assert items[0].type == DocItemType.FUNCTION


# ---------------------------------------------------------------------------
# Substring tier
# ---------------------------------------------------------------------------


def test_substring_match(doc_cache):
    _, items = doc_cache.search_documentation("src/foo.py", "parse")
    assert len(items) == 1
    assert items[0].name == "parse_data"


def test_substring_prefers_correct_type(tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "doc_cache"),
            start_with_clean_cache=True,
        )
    )
    file_doc = FileDoc(
        path="src/bar.py",
        type=FileDocType.CODE,
        description="Bar module.",
        items=[
            DocItem(
                name="parse_helper",
                type=DocItemType.CLASS,
                description="A class.",
            ),
            DocItem(
                name="parse_data",
                type=DocItemType.FUNCTION,
                description="A function.",
            ),
        ],
    )
    cache.set_file_documentation("src/bar.py", file_doc)

    # With FUNCTION type filter: tier 5 (substring + type) returns only parse_data
    _, items = cache.search_documentation("src/bar.py", "parse", DocItemType.FUNCTION)
    assert all(i.type == DocItemType.FUNCTION for i in items)
    assert any(i.name == "parse_data" for i in items)


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------


def test_no_match_returns_empty_list(doc_cache):
    file_doc, items = doc_cache.search_documentation("src/foo.py", "nonexistent")
    assert isinstance(file_doc, FileDoc)
    assert items == []
