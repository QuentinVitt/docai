import pytest
from unittest.mock import AsyncMock, MagicMock

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    DocItem,
    DocItemRef,
    DocItemType,
    FileDoc,
    FileDocType,
)
from docai.documentation.file_documentation import (
    _build_entity_context,
    _validate_file_doc,
    document_file,
)
from docai.llm.service import LLMService


@pytest.fixture
def doc_cache(tmp_path):
    return DocumentationCache(
        DocumentationCacheConfig(
            cache_dir=str(tmp_path / "doc_cache"),
            start_with_clean_cache=True,
        ),
        project_path=str(tmp_path),
    )


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMService)
    llm.generate_agent = AsyncMock(
        return_value=({"description": "A module description."}, MagicMock())
    )
    return llm


# ---------------------------------------------------------------------------
# _validate_file_doc
# ---------------------------------------------------------------------------


def test_validate_file_doc_valid():
    assert _validate_file_doc({"description": "Handles user auth."}) is None


def test_validate_file_doc_not_dict():
    assert _validate_file_doc("text") == "Expected a JSON object."


def test_validate_file_doc_empty_description():
    err = _validate_file_doc({"description": "  "})
    assert err is not None
    assert "description" in err


def test_validate_file_doc_missing_description():
    err = _validate_file_doc({})
    assert err is not None


# ---------------------------------------------------------------------------
# _build_entity_context
# ---------------------------------------------------------------------------


def test_build_entity_context_with_cached_entities(doc_cache):
    ref = DocItemRef(name="my_func", type=DocItemType.FUNCTION)
    doc_item = DocItem(name="my_func", type=DocItemType.FUNCTION, description="Does things.")
    doc_cache.set_entity_documentation("src/foo.py", ref, doc_item)

    result = _build_entity_context("src/foo.py", [ref], doc_cache)
    assert "my_func" in result
    assert "Does things." in result


def test_build_entity_context_no_entities_in_cache(doc_cache):
    ref = DocItemRef(name="my_func", type=DocItemType.FUNCTION)
    result = _build_entity_context("src/foo.py", [ref], doc_cache)
    assert result == "No entity documentation available."


def test_build_entity_context_empty_list(doc_cache):
    result = _build_entity_context("src/foo.py", [], doc_cache)
    assert result == "No entity documentation available."


def test_build_entity_context_multiple_entities(doc_cache):
    refs = [
        DocItemRef(name="func_a", type=DocItemType.FUNCTION),
        DocItemRef(name="func_b", type=DocItemType.FUNCTION),
    ]
    for ref in refs:
        doc_cache.set_entity_documentation(
            "src/foo.py",
            ref,
            DocItem(name=ref.name, type=DocItemType.FUNCTION, description=f"{ref.name} docs."),
        )

    result = _build_entity_context("src/foo.py", refs, doc_cache)
    assert "func_a" in result
    assert "func_b" in result


# ---------------------------------------------------------------------------
# document_file — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_file_returns_cached(doc_cache, mock_llm, tmp_path):
    cached = FileDoc(
        path="src/foo.py",
        type=FileDocType.CODE,
        description="Cached description.",
        items=[],
    )
    doc_cache.set_file_documentation("src/foo.py", cached)

    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "entities": [], "dependencies": set()}
    result = await document_file(str(tmp_path), "src/foo.py", file_info, mock_llm, doc_cache)

    mock_llm.generate_agent.assert_not_called()
    assert result.description == "Cached description."


# ---------------------------------------------------------------------------
# document_file — SKIPPED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_file_skipped_returns_empty_doc(doc_cache, mock_llm, tmp_path):
    file_info = {"file_doc_type": FileDocType.SKIPPED, "file_type": "png", "entities": []}
    result = await document_file(str(tmp_path), "image.png", file_info, mock_llm, doc_cache)

    mock_llm.generate_agent.assert_not_called()
    assert result.description == ""
    assert result.type == FileDocType.SKIPPED
    # Should be cached
    assert doc_cache.get_file_documentation("image.png") is not None


@pytest.mark.asyncio
async def test_document_file_none_type_returns_empty_doc(doc_cache, mock_llm, tmp_path):
    file_info = {"file_doc_type": None, "file_type": "xyz", "entities": []}
    result = await document_file(str(tmp_path), "unknown.xyz", file_info, mock_llm, doc_cache)

    mock_llm.generate_agent.assert_not_called()
    assert result.description == ""
    assert result.type == FileDocType.SKIPPED


# ---------------------------------------------------------------------------
# document_file — CODE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_file_code_calls_llm_and_caches(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def hello(): pass")

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Module with hello function."}, MagicMock())
    )

    file_info = {
        "file_doc_type": FileDocType.CODE,
        "file_type": "py",
        "entities": [],
        "dependencies": set(),
    }
    result = await document_file(str(tmp_path), "src/foo.py", file_info, mock_llm, doc_cache)

    assert result.description == "Module with hello function."
    assert result.type == FileDocType.CODE
    assert result.path == "src/foo.py"
    mock_llm.generate_agent.assert_called_once()
    assert doc_cache.get_file_documentation("src/foo.py") is not None


# ---------------------------------------------------------------------------
# document_file — CONFIG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_file_config_calls_llm_and_caches(doc_cache, mock_llm, tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "app.yaml").write_text("debug: false")

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "App configuration."}, MagicMock())
    )

    file_info = {
        "file_doc_type": FileDocType.CONFIG,
        "file_type": "yaml",
        "entities": [],
        "dependencies": set(),
    }
    result = await document_file(str(tmp_path), "cfg/app.yaml", file_info, mock_llm, doc_cache)

    assert result.description == "App configuration."
    assert result.type == FileDocType.CONFIG


# ---------------------------------------------------------------------------
# document_file — DOCS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_file_docs_calls_llm_and_caches(doc_cache, mock_llm, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\nThis is a guide.")

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Usage guide."}, MagicMock())
    )

    file_info = {
        "file_doc_type": FileDocType.DOCS,
        "file_type": "md",
        "entities": [],
        "dependencies": set(),
    }
    result = await document_file(str(tmp_path), "docs/guide.md", file_info, mock_llm, doc_cache)

    assert result.description == "Usage guide."
    assert result.type == FileDocType.DOCS


# ---------------------------------------------------------------------------
# document_file — entities included in FileDoc.items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_file_includes_entities_in_items(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def hello(): pass")

    refs = [
        DocItemRef(name="hello", type=DocItemType.FUNCTION),
        DocItemRef(name="world", type=DocItemType.FUNCTION),
    ]

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Module."}, MagicMock())
    )

    file_info = {
        "file_doc_type": FileDocType.CODE,
        "file_type": "py",
        "entities": refs,
        "dependencies": set(),
    }
    result = await document_file(str(tmp_path), "src/foo.py", file_info, mock_llm, doc_cache)

    assert len(result.items) == 2
    assert {r.name for r in result.items} == {"hello", "world"}
