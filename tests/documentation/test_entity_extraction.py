import pytest
from unittest.mock import AsyncMock, MagicMock

from docai.documentation.datatypes import DocItemType, FileDocType
from docai.documentation.entity_extraction import (
    _check_entity_list,
    _validate_code_entities,
    _validate_config_entities,
    _validate_unknown_entities,
    get_entities,
    get_entities_from_code_file,
    get_entities_from_config_file,
)
from docai.llm.service import LLMService


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMService)
    llm.generate = AsyncMock(return_value=({"entities": []}, MagicMock()))
    return llm


# ---------------------------------------------------------------------------
# _check_entity_list
# ---------------------------------------------------------------------------


def test_check_entity_list_valid_function():
    entities = [{"name": "my_func", "type": "function"}]
    assert _check_entity_list(entities, code_only=True) == []


def test_check_entity_list_valid_method_with_parent():
    entities = [{"name": "get_user", "type": "method", "parent": "UserService"}]
    assert _check_entity_list(entities, code_only=True) == []


def test_check_entity_list_empty_name():
    entities = [{"name": "", "type": "function"}]
    errors = _check_entity_list(entities, code_only=True)
    assert any("empty name" in e for e in errors)


def test_check_entity_list_private_in_code_only():
    entities = [{"name": "_private", "type": "function"}]
    errors = _check_entity_list(entities, code_only=True)
    assert any("_" in e for e in errors)


def test_check_entity_list_private_allowed_when_not_code_only():
    entities = [{"name": "_private", "type": "constant"}]
    errors = _check_entity_list(entities, code_only=False)
    assert errors == []


def test_check_entity_list_method_missing_parent():
    entities = [{"name": "my_method", "type": "method"}]
    errors = _check_entity_list(entities, code_only=True)
    assert any("parent" in e for e in errors)


def test_check_entity_list_non_method_with_parent_code_only():
    entities = [{"name": "my_func", "type": "function", "parent": "SomeClass"}]
    errors = _check_entity_list(entities, code_only=True)
    assert any("parent" in e for e in errors)


def test_check_entity_list_non_method_with_parent_not_code_only():
    # Not code_only — parent is allowed for config nested keys
    entities = [{"name": "host", "type": "constant", "parent": "database"}]
    errors = _check_entity_list(entities, code_only=False)
    assert errors == []


def test_check_entity_list_unsupported_type():
    entities = [{"name": "x", "type": "unknown_type"}]
    errors = _check_entity_list(entities, code_only=True)
    assert any("supported entity type" in e for e in errors)


# ---------------------------------------------------------------------------
# _validate_code_entities
# ---------------------------------------------------------------------------


def test_validate_code_entities_valid():
    result = {"entities": [{"name": "foo", "type": "function"}]}
    assert _validate_code_entities(result) is None


def test_validate_code_entities_not_dict():
    assert _validate_code_entities("text") == "Expected a JSON object"


def test_validate_code_entities_entities_not_list():
    assert _validate_code_entities({"entities": "not_list"}) is not None


def test_validate_code_entities_private_name():
    result = {"entities": [{"name": "_private", "type": "function"}]}
    err = _validate_code_entities(result)
    assert err is not None
    assert "Entity validation errors" in err


def test_validate_code_entities_empty_entities():
    assert _validate_code_entities({"entities": []}) is None


# ---------------------------------------------------------------------------
# _validate_config_entities
# ---------------------------------------------------------------------------


def test_validate_config_entities_valid():
    result = {"entities": [{"name": "debug", "type": "constant"}]}
    assert _validate_config_entities(result) is None


def test_validate_config_entities_invalid_type():
    result = {"entities": [{"name": "my_func", "type": "function"}]}
    err = _validate_config_entities(result)
    assert err is not None
    assert "datatype" in err or "constant" in err


def test_validate_config_entities_not_dict():
    assert _validate_config_entities(42) == "Expected a JSON object"


# ---------------------------------------------------------------------------
# _validate_unknown_entities
# ---------------------------------------------------------------------------


def test_validate_unknown_entities_valid_code():
    result = {
        "doc_type": "code",
        "entities": [{"name": "my_func", "type": "function"}],
    }
    assert _validate_unknown_entities(result) is None


def test_validate_unknown_entities_valid_other_empty():
    result = {"doc_type": "other", "entities": []}
    assert _validate_unknown_entities(result) is None


def test_validate_unknown_entities_other_with_entities():
    result = {"doc_type": "other", "entities": [{"name": "x", "type": "constant"}]}
    err = _validate_unknown_entities(result)
    assert err is not None
    assert "other" in err


def test_validate_unknown_entities_bad_doc_type():
    result = {"doc_type": "unknown_type", "entities": []}
    err = _validate_unknown_entities(result)
    assert err is not None
    assert "doc_type" in err


def test_validate_unknown_entities_not_dict():
    assert _validate_unknown_entities("text") == "Expected a JSON object"


def test_validate_unknown_entities_config_invalid_type():
    result = {
        "doc_type": "config",
        "entities": [{"name": "my_func", "type": "function"}],
    }
    err = _validate_unknown_entities(result)
    assert err is not None


# ---------------------------------------------------------------------------
# get_entities — routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entities_docs_returns_empty(mock_llm, tmp_path):
    file_info = {"file_doc_type": FileDocType.DOCS}
    result = await get_entities(str(tmp_path), "README.md", file_info, mock_llm)
    assert result == []
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_get_entities_other_returns_empty(mock_llm, tmp_path):
    file_info = {"file_doc_type": FileDocType.OTHER}
    result = await get_entities(str(tmp_path), "data.csv", file_info, mock_llm)
    assert result == []


@pytest.mark.asyncio
async def test_get_entities_skipped_returns_empty(mock_llm, tmp_path):
    file_info = {"file_doc_type": FileDocType.SKIPPED}
    result = await get_entities(str(tmp_path), "image.png", file_info, mock_llm)
    assert result == []


@pytest.mark.asyncio
async def test_get_entities_code_calls_llm(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def hello(): pass")

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate = AsyncMock(
        return_value=({"entities": [{"name": "hello", "type": "function"}]}, MagicMock())
    )

    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py"}
    result = await get_entities(str(tmp_path), "src/foo.py", file_info, mock_llm)

    assert len(result) == 1
    assert result[0].name == "hello"
    assert result[0].type == DocItemType.FUNCTION


@pytest.mark.asyncio
async def test_get_entities_config_calls_llm(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "app.yaml").write_text("debug: false")

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate = AsyncMock(
        return_value=({"entities": [{"name": "debug", "type": "constant"}]}, MagicMock())
    )

    file_info = {"file_doc_type": FileDocType.CONFIG, "file_type": "yaml"}
    result = await get_entities(str(tmp_path), "cfg/app.yaml", file_info, mock_llm)

    assert len(result) == 1
    assert result[0].name == "debug"
    assert result[0].type == DocItemType.CONSTANT


@pytest.mark.asyncio
async def test_get_entities_code_no_llm_raises(tmp_path):
    file_info = {"file_doc_type": FileDocType.CODE}
    with pytest.raises(ValueError, match="LLMService is required"):
        await get_entities(str(tmp_path), "foo.py", file_info, None)


# ---------------------------------------------------------------------------
# get_entities_from_code_file — parses result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entities_from_code_file_returns_refs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("class Foo:\n    def bar(self): pass")

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate = AsyncMock(
        return_value=(
            {
                "entities": [
                    {"name": "Foo", "type": "class"},
                    {"name": "bar", "type": "method", "parent": "Foo"},
                ]
            },
            MagicMock(),
        )
    )

    file_info = {"file_type": "py"}
    result = await get_entities_from_code_file(str(tmp_path), "src/foo.py", file_info, mock_llm)

    assert len(result) == 2
    names = {r.name for r in result}
    assert names == {"Foo", "bar"}
    method = next(r for r in result if r.name == "bar")
    assert method.parent == "Foo"


@pytest.mark.asyncio
async def test_get_entities_from_code_file_empty_entities(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "empty.py").write_text("# nothing here")

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate = AsyncMock(return_value=({"entities": []}, MagicMock()))

    file_info = {"file_type": "py"}
    result = await get_entities_from_code_file(str(tmp_path), "src/empty.py", file_info, mock_llm)
    assert result == []


# ---------------------------------------------------------------------------
# get_entities_from_config_file — parses result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entities_from_config_file_returns_refs(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "app.yaml").write_text("database:\n  host: localhost\ndebug: false")

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate = AsyncMock(
        return_value=(
            {
                "entities": [
                    {"name": "database", "type": "datatype"},
                    {"name": "host", "type": "constant", "parent": "database"},
                    {"name": "debug", "type": "constant"},
                ]
            },
            MagicMock(),
        )
    )

    file_info = {"file_type": "yaml"}
    result = await get_entities_from_config_file(str(tmp_path), "cfg/app.yaml", file_info, mock_llm)

    assert len(result) == 3
    section = next(r for r in result if r.name == "database")
    assert section.type == DocItemType.DATATYPE
    nested = next(r for r in result if r.name == "host")
    assert nested.parent == "database"
