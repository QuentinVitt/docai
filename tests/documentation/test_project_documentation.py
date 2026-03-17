import pytest
from unittest.mock import AsyncMock, MagicMock

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import PackageDoc, ProjectDoc
from docai.documentation.project_documentation import (
    _validate_project_doc,
    document_project,
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
        return_value=({"description": "A project description."}, MagicMock())
    )
    return llm


# ---------------------------------------------------------------------------
# _validate_project_doc
# ---------------------------------------------------------------------------


def test_validate_project_doc_valid():
    assert _validate_project_doc({"description": "An AI documentation tool."}) is None


def test_validate_project_doc_not_dict():
    assert _validate_project_doc("text") == "Expected a JSON object."


def test_validate_project_doc_empty_description():
    err = _validate_project_doc({"description": "  "})
    assert err is not None
    assert "description" in err


def test_validate_project_doc_missing_description():
    err = _validate_project_doc({})
    assert err is not None


# ---------------------------------------------------------------------------
# document_project — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_project_returns_cached(doc_cache, mock_llm, tmp_path):
    cached = ProjectDoc(
        name="MyProject",
        description="Cached project description.",
        packages=["src/core"],
    )
    doc_cache.set_project_documentation("MyProject", str(tmp_path), cached)

    result = await document_project(
        str(tmp_path), "MyProject", ["src/core"], mock_llm, doc_cache
    )

    mock_llm.generate_agent.assert_not_called()
    assert result.description == "Cached project description."


# ---------------------------------------------------------------------------
# document_project — calls LLM and caches result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_project_calls_llm_and_caches(doc_cache, mock_llm, tmp_path):
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "CLI tool for AI-powered documentation."}, MagicMock())
    )

    result = await document_project(
        str(tmp_path), "DocAI", ["src/docai"], mock_llm, doc_cache
    )

    mock_llm.generate_agent.assert_called_once()
    assert result.description == "CLI tool for AI-powered documentation."
    assert result.name == "DocAI"
    assert result.packages == ["src/docai"]
    assert doc_cache.get_project_documentation("DocAI") is not None


# ---------------------------------------------------------------------------
# document_project — builds context from package docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_project_includes_package_context(doc_cache, mock_llm, tmp_path):
    pkg_doc = PackageDoc(
        path="src/docai",
        description="Core documentation logic.",
        files=["src/docai/main.py"],
        packages=[],
    )
    doc_cache.set_package_documentation("src/docai", pkg_doc)

    captured_prompts: list[str] = []

    async def mock_generate_agent(**kwargs):
        captured_prompts.append(kwargs.get("prompt", ""))
        return {"description": "DocAI project."}, MagicMock()

    mock_llm.generate_agent = mock_generate_agent

    await document_project(str(tmp_path), "DocAI", ["src/docai"], mock_llm, doc_cache)

    assert len(captured_prompts) == 1
    assert "Core documentation logic." in captured_prompts[0]


# ---------------------------------------------------------------------------
# document_project — no package docs available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_project_no_package_docs(doc_cache, mock_llm, tmp_path):
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "A project with no package docs yet."}, MagicMock())
    )

    result = await document_project(
        str(tmp_path), "MyProject", ["src/core"], mock_llm, doc_cache
    )

    # Should succeed even if no package docs are cached
    assert result.description == "A project with no package docs yet."


# ---------------------------------------------------------------------------
# document_project — multiple top-level packages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_project_multiple_packages(doc_cache, mock_llm, tmp_path):
    for pkg_path, desc in [
        ("src/api", "API layer."),
        ("src/core", "Core logic."),
        ("src/utils", "Utilities."),
    ]:
        doc_cache.set_package_documentation(
            pkg_path,
            PackageDoc(path=pkg_path, description=desc, files=[], packages=[]),
        )

    captured_prompts: list[str] = []

    async def mock_generate_agent(**kwargs):
        captured_prompts.append(kwargs.get("prompt", ""))
        return {"description": "Full project."}, MagicMock()

    mock_llm.generate_agent = mock_generate_agent

    result = await document_project(
        str(tmp_path), "BigProject", ["src/api", "src/core", "src/utils"], mock_llm, doc_cache
    )

    prompt = captured_prompts[0]
    assert "API layer." in prompt
    assert "Core logic." in prompt
    assert "Utilities." in prompt
    assert result.packages == ["src/api", "src/core", "src/utils"]
