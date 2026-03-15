import pytest

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    Attribute,
    DocItem,
    DocItemType,
    DocumentationCacheConfig,
    FileDoc,
    FileDocType,
    Parameter,
    RaisesEntry,
    ReturnValue,
)
from docai.llm.agent_tools import _format_item, make_tool_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "app.py").write_text("def run(): pass\n")
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "utils.py").write_text("TIMEOUT = 30\n")
    return tmp_path


@pytest.fixture
def doc_cache(tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "doc_cache"),
            start_with_clean_cache=True,
        )
    )
    file_doc = FileDoc(
        path="app.py",
        type=FileDocType.CODE,
        description="Main application entry point.",
        items=[
            DocItem(
                name="run",
                type=DocItemType.FUNCTION,
                description="Starts the app.",
            ),
            DocItem(
                name="Config",
                type=DocItemType.CLASS,
                description="App config.",
            ),
        ],
    )
    cache.set_file_documentation("app.py", file_doc)
    return cache


@pytest.fixture
def registry(project_dir):
    return make_tool_registry(str(project_dir))


@pytest.fixture
def registry_with_cache(project_dir, doc_cache):
    return make_tool_registry(str(project_dir), doc_cache)


# ---------------------------------------------------------------------------
# search_in_project callable
# ---------------------------------------------------------------------------


def test_search_no_matches(registry):
    result = registry["search_in_project"]["callable"](query="xyz_not_here")
    assert result == "No matches for 'xyz_not_here'."


def test_search_no_matches_with_path(registry):
    result = registry["search_in_project"]["callable"](query="xyz_not_here", path="lib")
    assert result == "No matches for 'xyz_not_here' under 'lib'."


def test_search_result_line_format(registry):
    result = registry["search_in_project"]["callable"](query="run")
    lines = result.splitlines()
    # Skip header line, check result lines have "path:lineno: content" format
    result_lines = [l for l in lines[1:] if l.strip()]
    for line in result_lines:
        parts = line.split(":", 2)
        assert len(parts) == 3, f"Expected path:lineno: content, got: {line!r}"
        assert parts[1].strip().isdigit()


def test_search_header_present(registry):
    result = registry["search_in_project"]["callable"](query="run")
    assert result.startswith("Found ")
    assert "matches for 'run'" in result


def test_search_not_truncated_no_notice(registry):
    result = registry["search_in_project"]["callable"](query="run")
    assert "truncated" not in result.lower()
    assert "+" not in result.splitlines()[0]


def test_search_truncated_shows_notice_and_plus(project_dir, monkeypatch):
    fake_matches = [("app.py", 1, "def run(): pass"), ("lib/utils.py", 1, "TIMEOUT = 30")]
    monkeypatch.setattr(
        "docai.llm.agent_tools._search_in_project",
        lambda *a, **kw: (fake_matches, True),
    )
    reg = make_tool_registry(str(project_dir))
    result = reg["search_in_project"]["callable"](query="anything")
    assert "2+" in result
    assert "truncated" in result.lower()


# ---------------------------------------------------------------------------
# get_documentation callable
# ---------------------------------------------------------------------------


def test_no_cache_returns_not_available(registry):
    result = registry["get_documentation"]["callable"](path="app.py")
    assert result == "Documentation is not available yet."


def test_file_not_in_cache(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](path="missing.py")
    assert result == "No documentation available for 'missing.py'."


def test_file_overview_no_entity(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](path="app.py")
    assert "app.py" in result
    assert "Entities:" in result
    assert "run" in result
    assert "Config" in result


def test_file_overview_code_no_items(project_dir, tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "empty_cache"),
            start_with_clean_cache=True,
        )
    )
    cache.set_file_documentation(
        "app.py",
        FileDoc(
            path="app.py",
            type=FileDocType.CODE,
            description="Empty module.",
            items=[],
        ),
    )
    reg = make_tool_registry(str(project_dir), cache)
    result = reg["get_documentation"]["callable"](path="app.py")
    assert "No entities documented." in result


def test_entity_single_match_includes_file_header(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        path="app.py", entity_name="run"
    )
    # File header
    assert "app.py" in result
    assert "Main application entry point." in result
    # Entity detail
    assert "Starts the app." in result


def test_entity_not_found_with_available_list(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        path="app.py", entity_name="nonexistent"
    )
    assert "No documentation found for 'nonexistent'" in result
    assert "Available entities" in result
    assert "run" in result


def test_entity_not_found_no_items(project_dir, tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "empty_cache2"),
            start_with_clean_cache=True,
        )
    )
    cache.set_file_documentation(
        "app.py",
        FileDoc(
            path="app.py",
            type=FileDocType.CODE,
            description="Empty.",
            items=[],
        ),
    )
    reg = make_tool_registry(str(project_dir), cache)
    result = reg["get_documentation"]["callable"](path="app.py", entity_name="foo")
    assert "No documentation found for 'foo'" in result
    assert "Available entities" not in result


def test_entity_multiple_matches_numbered(project_dir, tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "multi_cache"),
            start_with_clean_cache=True,
        )
    )
    # Both "process_data" and "process_file" contain "process" → 2 substring matches
    cache.set_file_documentation(
        "app.py",
        FileDoc(
            path="app.py",
            type=FileDocType.CODE,
            description="Module.",
            items=[
                DocItem(
                    name="process_data",
                    type=DocItemType.FUNCTION,
                    description="Processes data.",
                ),
                DocItem(
                    name="process_file",
                    type=DocItemType.FUNCTION,
                    description="Processes a file.",
                ),
            ],
        ),
    )
    reg = make_tool_registry(str(project_dir), cache)
    result = reg["get_documentation"]["callable"](path="app.py", entity_name="process")
    assert "1. " in result
    assert "2. " in result


def test_invalid_entity_type(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        path="app.py", entity_name="run", entity_type="widget"
    )
    assert "Unknown entity_type 'widget'" in result
    assert "function" in result  # valid types listed


# ---------------------------------------------------------------------------
# _format_item helper
# ---------------------------------------------------------------------------


def _make_item(**kwargs) -> DocItem:
    defaults = dict(name="MyFunc", type=DocItemType.FUNCTION, description="Does stuff.")
    return DocItem(**{**defaults, **kwargs})


def test_format_item_minimal():
    lines = _format_item(_make_item())
    joined = "\n".join(lines)
    assert "MyFunc" in joined
    assert "function" in joined
    assert "Does stuff." in joined


def test_format_item_with_parent():
    item = _make_item(name="do_thing", type=DocItemType.METHOD, parent="MyClass")
    lines = _format_item(item)
    assert "parent: MyClass" in lines[0]


def test_format_item_with_parameters():
    item = _make_item(
        parameters=[Parameter(name="x", type_hint="int", description="A number.")]
    )
    joined = "\n".join(_format_item(item))
    assert "Parameters:" in joined
    assert "x" in joined


def test_format_item_with_returns():
    item = _make_item(returns=ReturnValue(type_hint="str", description="The result."))
    joined = "\n".join(_format_item(item))
    assert "Returns" in joined
    assert "The result." in joined


def test_format_item_with_raises():
    item = _make_item(
        raises=[RaisesEntry(exception="ValueError", description="If invalid.")]
    )
    joined = "\n".join(_format_item(item))
    assert "Raises:" in joined
    assert "ValueError" in joined


def test_format_item_with_side_effects():
    item = _make_item(side_effects="Writes to disk.")
    joined = "\n".join(_format_item(item))
    assert "Side effects:" in joined
    assert "Writes to disk." in joined


def test_format_item_with_attributes():
    item = _make_item(
        type=DocItemType.CLASS,
        attributes=[Attribute(name="size", type_hint="int", description="The size.")],
    )
    joined = "\n".join(_format_item(item))
    assert "Attributes:" in joined
    assert "size" in joined


def test_format_item_with_dunder_methods():
    item = _make_item(type=DocItemType.CLASS, dunder_methods=["__init__", "__repr__"])
    joined = "\n".join(_format_item(item))
    assert "Dunder methods:" in joined
    assert "__init__" in joined


def test_format_item_header_prefix():
    item = _make_item(name="MyClass", type=DocItemType.CLASS)
    lines = _format_item(item, header_prefix="3. ")
    assert lines[0].startswith("3. MyClass")
