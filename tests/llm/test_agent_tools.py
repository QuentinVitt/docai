import pytest

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    Attribute,
    DocItem,
    DocItemRef,
    DocItemType,
    FileDoc,
    FileDocType,
    Parameter,
    RaisesEntry,
    ReturnValue,
)
from docai.llm.agent_tools import make_tool_registry


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
        ),
        project_path=str(tmp_path),
    )
    refs = [
        DocItemRef(name="run", type=DocItemType.FUNCTION),
        DocItemRef(name="Config", type=DocItemType.CLASS),
    ]
    file_doc = FileDoc(
        path="app.py",
        type=FileDocType.CODE,
        description="Main application entry point.",
        items=refs,
    )
    cache.set_file_documentation("app.py", file_doc)
    cache.set_entity_documentation(
        "app.py",
        refs[0],
        DocItem(name="run", type=DocItemType.FUNCTION, description="Starts the app."),
    )
    cache.set_entity_documentation(
        "app.py",
        refs[1],
        DocItem(name="Config", type=DocItemType.CLASS, description="App config."),
    )
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
# get_documentation — level validation
# ---------------------------------------------------------------------------


def test_no_cache_returns_not_available(registry):
    result = registry["get_documentation"]["callable"](level="file", path="app.py")
    assert result == "Documentation is not available yet."


def test_unknown_level(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](level="unknown", path="app.py")
    assert "Unknown level" in result


# ---------------------------------------------------------------------------
# get_documentation — file level
# ---------------------------------------------------------------------------


def test_file_level_overview(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="file", path="app.py"
    )
    assert "app.py" in result
    assert "Entities:" in result
    assert "run" in result
    assert "Config" in result


def test_file_not_in_cache(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="file", path="missing.py"
    )
    assert "No documentation available for 'missing.py'" in result


def test_file_overview_no_items(project_dir, tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "empty_cache"),
            start_with_clean_cache=True,
        ),
        project_path=str(tmp_path),
    )
    cache.set_file_documentation(
        "app.py",
        FileDoc(path="app.py", type=FileDocType.CODE, description="Empty module.", items=[]),
    )
    reg = make_tool_registry(str(project_dir), cache)
    result = reg["get_documentation"]["callable"](level="file", path="app.py")
    assert "app.py" in result
    assert "Empty module." in result


# ---------------------------------------------------------------------------
# get_documentation — entity level
# ---------------------------------------------------------------------------


def test_entity_level_all(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="entity", path="app.py"
    )
    assert "run" in result
    assert "Config" in result
    assert "Starts the app." in result
    assert "App config." in result


def test_entity_level_single_query(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="entity", path="app.py", queries=[{"name": "run"}]
    )
    assert "Starts the app." in result


def test_entity_level_no_match(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="entity", path="app.py", queries=[{"name": "nonexistent"}]
    )
    assert "No entities found" in result


def test_entity_level_invalid_type(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="entity", path="app.py", queries=[{"name": "run", "type": "widget"}]
    )
    assert "Unknown entity type 'widget'" in result
    assert "function" in result


def test_entity_level_multiple_matches(project_dir, tmp_path):
    cache = DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "multi_cache"),
            start_with_clean_cache=True,
        ),
        project_path=str(tmp_path),
    )
    refs = [
        DocItemRef(name="process_data", type=DocItemType.FUNCTION),
        DocItemRef(name="process_file", type=DocItemType.FUNCTION),
    ]
    cache.set_file_documentation(
        "app.py",
        FileDoc(path="app.py", type=FileDocType.CODE, description="Module.", items=refs),
    )
    for ref in refs:
        cache.set_entity_documentation(
            "app.py",
            ref,
            DocItem(name=ref.name, type=ref.type, description=f"Processes {ref.name.split('_')[1]}."),
        )
    reg = make_tool_registry(str(project_dir), cache)
    result = reg["get_documentation"]["callable"](
        level="entity", path="app.py", queries=[{"name": "process"}]
    )
    assert "process_data" in result
    assert "process_file" in result
    assert "---" in result


# ---------------------------------------------------------------------------
# get_documentation — package level
# ---------------------------------------------------------------------------


def test_package_not_found(registry_with_cache):
    result = registry_with_cache["get_documentation"]["callable"](
        level="package", path="src"
    )
    assert "No package documentation found" in result


# ---------------------------------------------------------------------------
# DocItem __str__ (replaces _format_item tests)
# ---------------------------------------------------------------------------


def _make_item(**kwargs) -> DocItem:
    defaults = dict(name="MyFunc", type=DocItemType.FUNCTION, description="Does stuff.")
    return DocItem(**{**defaults, **kwargs})


def test_str_minimal():
    result = str(_make_item())
    assert "MyFunc" in result
    assert "function" in result
    assert "Does stuff." in result


def test_str_with_parent():
    item = _make_item(name="do_thing", type=DocItemType.METHOD, parent="MyClass")
    result = str(item)
    assert "(MyClass)" in result


def test_str_with_parameters():
    item = _make_item(
        parameters=[Parameter(name="x", type_hint="int", description="A number.")]
    )
    result = str(item)
    assert "Parameters:" in result
    assert "x" in result


def test_str_with_returns():
    item = _make_item(returns=ReturnValue(type_hint="str", description="The result."))
    result = str(item)
    assert "Returns" in result
    assert "The result." in result


def test_str_with_raises():
    item = _make_item(
        raises=[RaisesEntry(exception="ValueError", description="If invalid.")]
    )
    result = str(item)
    assert "Raises:" in result
    assert "ValueError" in result


def test_str_with_side_effects():
    item = _make_item(side_effects="Writes to disk.")
    result = str(item)
    assert "Side effects:" in result
    assert "Writes to disk." in result


def test_str_with_attributes():
    item = _make_item(
        type=DocItemType.CLASS,
        attributes=[Attribute(name="size", type_hint="int", description="The size.")],
    )
    result = str(item)
    assert "Attributes:" in result
    assert "size" in result


def test_str_with_dunder_methods():
    item = _make_item(type=DocItemType.CLASS, dunder_methods=["__init__", "__repr__"])
    result = str(item)
    assert "Dunder methods:" in result
    assert "__init__" in result
