import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.base import (
    create_file_documentation,
    file_type_map,
    identify_entities,
    set_file_doc_type,
)
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    DocItemRef,
    DocItemType,
    FileDoc,
    FileDocType,
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
    llm.generate = AsyncMock(return_value=({"entities": []}, MagicMock()))
    llm.generate_agent = AsyncMock(return_value=({"description": "A description."}, MagicMock()))
    return llm


# ---------------------------------------------------------------------------
# file_type_map
# ---------------------------------------------------------------------------


def test_file_type_map_code_extensions():
    assert file_type_map["py"] == FileDocType.CODE
    assert file_type_map["js"] == FileDocType.CODE
    assert file_type_map["ts"] == FileDocType.CODE
    assert file_type_map["rs"] == FileDocType.CODE
    assert file_type_map["go"] == FileDocType.CODE


def test_file_type_map_config_extensions():
    assert file_type_map["yaml"] == FileDocType.CONFIG
    assert file_type_map["json"] == FileDocType.CONFIG
    assert file_type_map["toml"] == FileDocType.CONFIG
    assert file_type_map["ini"] == FileDocType.CONFIG


def test_file_type_map_docs_extensions():
    assert file_type_map["md"] == FileDocType.DOCS
    assert file_type_map["rst"] == FileDocType.DOCS


def test_file_type_map_skipped_extensions():
    assert file_type_map["png"] == FileDocType.SKIPPED
    assert file_type_map["jpg"] == FileDocType.SKIPPED
    assert file_type_map["pdf"] == FileDocType.SKIPPED
    assert file_type_map["lock"] == FileDocType.SKIPPED
    assert file_type_map["pyc"] == FileDocType.SKIPPED


def test_file_type_map_other_extensions():
    assert file_type_map["csv"] == FileDocType.OTHER
    assert file_type_map["tsv"] == FileDocType.OTHER


# ---------------------------------------------------------------------------
# set_file_doc_type
# ---------------------------------------------------------------------------


def test_set_file_doc_type_known_extension():
    file_info = {"file_type": "py"}
    set_file_doc_type(file_info)
    assert file_info["file_doc_type"] == FileDocType.CODE


def test_set_file_doc_type_config():
    file_info = {"file_type": "yaml"}
    set_file_doc_type(file_info)
    assert file_info["file_doc_type"] == FileDocType.CONFIG


def test_set_file_doc_type_skipped():
    file_info = {"file_type": "png"}
    set_file_doc_type(file_info)
    assert file_info["file_doc_type"] == FileDocType.SKIPPED


def test_set_file_doc_type_unknown_extension():
    file_info = {"file_type": "xyz"}
    set_file_doc_type(file_info)
    assert file_info["file_doc_type"] is None


def test_set_file_doc_type_missing_file_type():
    file_info = {}
    set_file_doc_type(file_info)
    assert file_info["file_doc_type"] is None


# ---------------------------------------------------------------------------
# identify_entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identify_entities_uses_cache_when_available(doc_cache, mock_llm, tmp_path):
    # identify_entities checks cache first but always calls get_entities to refresh
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("class MyClass: pass")

    ref = DocItemRef(name="MyClass", type=DocItemType.CLASS)
    file_doc = FileDoc(
        path="src/foo.py",
        type=FileDocType.CODE,
        description="A module.",
        items=[ref],
    )
    doc_cache.set_file_documentation("src/foo.py", file_doc)

    mock_llm.generate = AsyncMock(
        return_value=({"entities": [{"name": "MyClass", "type": "class"}]}, MagicMock())
    )

    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py"}
    await identify_entities(str(tmp_path), "src/foo.py", file_info, mock_llm, doc_cache)

    assert "entities" in file_info
    assert file_info["entities"][0].name == "MyClass"


@pytest.mark.asyncio
async def test_identify_entities_calls_get_entities_on_cache_miss(doc_cache, mock_llm, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def hello(): pass")

    mock_llm.generate = AsyncMock(
        return_value=({"entities": [{"name": "hello", "type": "function"}]}, MagicMock())
    )

    file_info = {"file_doc_type": FileDocType.CODE, "file_type": "py"}
    await identify_entities(str(tmp_path), "src/foo.py", file_info, mock_llm, doc_cache)

    assert "entities" in file_info
    assert len(file_info["entities"]) == 1
    assert file_info["entities"][0].name == "hello"


@pytest.mark.asyncio
async def test_identify_entities_no_llm_call_for_docs_type(doc_cache):
    file_info = {"file_doc_type": FileDocType.DOCS, "file_type": "md"}
    llm = MagicMock(spec=LLMService)
    llm.generate = AsyncMock()

    await identify_entities(".", "README.md", file_info, llm, doc_cache)

    llm.generate.assert_not_called()
    assert file_info["entities"] == []


# ---------------------------------------------------------------------------
# create_file_documentation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_file_documentation_documents_entities_and_file(doc_cache, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def hello(): pass")

    ref = DocItemRef(name="hello", type=DocItemType.FUNCTION)
    file_info = {
        "file_doc_type": FileDocType.CODE,
        "file_type": "py",
        "entities": [ref],
        "dependencies": set(),
    }

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "A function."}, MagicMock())
    )

    await create_file_documentation(str(tmp_path), "src/foo.py", file_info, mock_llm, doc_cache)

    # generate_agent should be called once for entity + once for file
    assert mock_llm.generate_agent.call_count == 2

    # File doc should be cached
    file_doc = doc_cache.get_file_documentation("src/foo.py")
    assert file_doc is not None
    assert file_doc.description == "A function."


@pytest.mark.asyncio
async def test_create_file_documentation_no_entities(doc_cache, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bar.py").write_text("# empty")

    file_info = {
        "file_doc_type": FileDocType.CODE,
        "file_type": "py",
        "entities": [],
        "dependencies": set(),
    }

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Empty module."}, MagicMock())
    )

    await create_file_documentation(str(tmp_path), "src/bar.py", file_info, mock_llm, doc_cache)

    # Only called once for the file (no entities)
    assert mock_llm.generate_agent.call_count == 1
