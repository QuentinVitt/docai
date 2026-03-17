import pytest
from unittest.mock import AsyncMock, MagicMock

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    DocItem,
    DocItemRef,
    DocItemType,
    FileDocType,
)
from docai.documentation.entity_documentation import (
    _validate_code_callable_doc,
    _validate_code_class_doc,
    _validate_description_only,
    document_entity,
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
    llm.generate_agent = AsyncMock(return_value=({"description": "A description."}, MagicMock()))
    return llm


# ---------------------------------------------------------------------------
# _validate_code_callable_doc
# ---------------------------------------------------------------------------


def test_validate_code_callable_valid_minimal():
    assert _validate_code_callable_doc({"description": "Does something."}) is None


def test_validate_code_callable_valid_full():
    result = {
        "description": "Processes data.",
        "parameters": [{"name": "x", "description": "input value"}],
        "returns": {"description": "processed result"},
        "raises": [{"exception": "ValueError", "description": "on bad input"}],
    }
    assert _validate_code_callable_doc(result) is None


def test_validate_code_callable_not_dict():
    assert _validate_code_callable_doc("not a dict") == "Expected a JSON object."


def test_validate_code_callable_missing_description():
    err = _validate_code_callable_doc({"description": "  "})
    assert err is not None
    assert "description" in err


def test_validate_code_callable_parameter_missing_name():
    result = {"description": "ok", "parameters": [{"description": "something"}]}
    err = _validate_code_callable_doc(result)
    assert err is not None
    assert "name" in err


def test_validate_code_callable_parameter_missing_description():
    result = {"description": "ok", "parameters": [{"name": "x", "description": ""}]}
    err = _validate_code_callable_doc(result)
    assert err is not None
    assert "description" in err


def test_validate_code_callable_returns_missing_description():
    result = {"description": "ok", "returns": {"description": ""}}
    err = _validate_code_callable_doc(result)
    assert err is not None
    assert "Returns" in err or "description" in err


def test_validate_code_callable_raises_missing_exception():
    result = {"description": "ok", "raises": [{"description": "something"}]}
    err = _validate_code_callable_doc(result)
    assert err is not None
    assert "exception" in err


def test_validate_code_callable_raises_missing_description():
    result = {"description": "ok", "raises": [{"exception": "ValueError", "description": ""}]}
    err = _validate_code_callable_doc(result)
    assert err is not None
    assert "description" in err


# ---------------------------------------------------------------------------
# _validate_code_class_doc
# ---------------------------------------------------------------------------


def test_validate_code_class_valid_minimal():
    assert _validate_code_class_doc({"description": "A class."}) is None


def test_validate_code_class_valid_with_attributes():
    result = {
        "description": "A class.",
        "attributes": [{"name": "value", "description": "stored value"}],
    }
    assert _validate_code_class_doc(result) is None


def test_validate_code_class_not_dict():
    assert _validate_code_class_doc("string") == "Expected a JSON object."


def test_validate_code_class_missing_description():
    err = _validate_code_class_doc({"description": ""})
    assert err is not None


def test_validate_code_class_attribute_missing_name():
    result = {"description": "ok", "attributes": [{"description": "something"}]}
    err = _validate_code_class_doc(result)
    assert err is not None
    assert "name" in err


def test_validate_code_class_attribute_missing_description():
    result = {"description": "ok", "attributes": [{"name": "x", "description": ""}]}
    err = _validate_code_class_doc(result)
    assert err is not None
    assert "description" in err


# ---------------------------------------------------------------------------
# _validate_description_only
# ---------------------------------------------------------------------------


def test_validate_description_only_valid():
    assert _validate_description_only({"description": "Something."}) is None


def test_validate_description_only_not_dict():
    assert _validate_description_only("text") == "Expected a JSON object."


def test_validate_description_only_empty_description():
    err = _validate_description_only({"description": "   "})
    assert err is not None
    assert "description" in err


def test_validate_description_only_missing_description():
    err = _validate_description_only({})
    assert err is not None


# ---------------------------------------------------------------------------
# document_entity — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_entity_returns_cached(doc_cache, mock_llm, tmp_path):
    ref = DocItemRef(name="my_func", type=DocItemType.FUNCTION)
    cached_item = DocItem(
        name="my_func", type=DocItemType.FUNCTION, description="Cached description."
    )
    doc_cache.set_entity_documentation("src/foo.py", ref, cached_item)

    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "dependencies": set()}
    result = await document_entity(str(tmp_path), "src/foo.py", file_info, ref, mock_llm, doc_cache)

    mock_llm.generate_agent.assert_not_called()
    assert result.description == "Cached description."


# ---------------------------------------------------------------------------
# document_entity — dispatch by file_doc_type + entity type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_entity_code_function(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def my_func(): pass")

    ref = DocItemRef(name="my_func", type=DocItemType.FUNCTION)
    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Runs something."}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "src/foo.py", file_info, ref, mock_llm, doc_cache)

    assert result.name == "my_func"
    assert result.type == DocItemType.FUNCTION
    assert result.description == "Runs something."
    # Should be cached
    assert doc_cache.get_entity_documentation("src/foo.py", ref) is not None


@pytest.mark.asyncio
async def test_document_entity_code_class(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("class MyClass: pass")

    ref = DocItemRef(name="MyClass", type=DocItemType.CLASS)
    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "A class.", "attributes": [], "dunder_methods": []}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "src/foo.py", file_info, ref, mock_llm, doc_cache)

    assert result.name == "MyClass"
    assert result.type == DocItemType.CLASS


@pytest.mark.asyncio
async def test_document_entity_code_method(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("class A:\n    def go(self): pass")

    ref = DocItemRef(name="go", type=DocItemType.METHOD, parent="A")
    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Runs."}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "src/foo.py", file_info, ref, mock_llm, doc_cache)

    assert result.parent == "A"


@pytest.mark.asyncio
async def test_document_entity_code_datatype(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("from dataclasses import dataclass\n@dataclass\nclass Cfg: x: int = 0")

    ref = DocItemRef(name="Cfg", type=DocItemType.DATATYPE)
    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Config dataclass.", "attributes": []}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "src/foo.py", file_info, ref, mock_llm, doc_cache)

    assert result.type == DocItemType.DATATYPE


@pytest.mark.asyncio
async def test_document_entity_code_constant(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("MAX = 100")

    ref = DocItemRef(name="MAX", type=DocItemType.CONSTANT)
    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Maximum value."}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "src/foo.py", file_info, ref, mock_llm, doc_cache)

    assert result.type == DocItemType.CONSTANT
    assert result.description == "Maximum value."


@pytest.mark.asyncio
async def test_document_entity_config_section(doc_cache, mock_llm, tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "app.yaml").write_text("database:\n  host: localhost")

    ref = DocItemRef(name="database", type=DocItemType.DATATYPE)
    file_info = {"file_doc_type": FileDocType.CONFIG, "file_type": "yaml", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "DB config section."}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "cfg/app.yaml", file_info, ref, mock_llm, doc_cache)

    assert result.type == DocItemType.DATATYPE
    assert result.description == "DB config section."


@pytest.mark.asyncio
async def test_document_entity_config_key(doc_cache, mock_llm, tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "app.yaml").write_text("debug: false")

    ref = DocItemRef(name="debug", type=DocItemType.CONSTANT)
    file_info = {"file_doc_type": FileDocType.CONFIG, "file_type": "yaml", "dependencies": set()}

    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Debug flag."}, MagicMock())
    )
    result = await document_entity(str(tmp_path), "cfg/app.yaml", file_info, ref, mock_llm, doc_cache)

    assert result.type == DocItemType.CONSTANT


# ---------------------------------------------------------------------------
# document_entity — unsupported combination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_entity_unsupported_combination_raises(doc_cache, mock_llm, tmp_path):
    ref = DocItemRef(name="something", type=DocItemType.FUNCTION)
    file_info = {"file_doc_type": FileDocType.DOCS, "file_type": "md", "dependencies": set()}

    with pytest.raises(ValueError, match="Unsupported combination"):
        await document_entity(str(tmp_path), "README.md", file_info, ref, mock_llm, doc_cache)
