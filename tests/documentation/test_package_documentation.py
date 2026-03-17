import pytest
from unittest.mock import AsyncMock, MagicMock

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    FileDoc,
    FileDocType,
    PackageDoc,
)
from docai.documentation.package_documentation import (
    _validate_package_doc,
    document_package,
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
        return_value=({"description": "A package description."}, MagicMock())
    )
    return llm


# ---------------------------------------------------------------------------
# _validate_package_doc
# ---------------------------------------------------------------------------


def test_validate_package_doc_valid():
    assert _validate_package_doc({"description": "Handles authentication."}) is None


def test_validate_package_doc_not_dict():
    assert _validate_package_doc("text") == "Expected a JSON object."


def test_validate_package_doc_empty_description():
    err = _validate_package_doc({"description": "   "})
    assert err is not None
    assert "description" in err


def test_validate_package_doc_missing_description():
    err = _validate_package_doc({})
    assert err is not None


# ---------------------------------------------------------------------------
# document_package — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_package_returns_cached(doc_cache, mock_llm, tmp_path):
    cached = PackageDoc(
        path="src/auth",
        description="Cached package description.",
        files=["src/auth/login.py"],
        packages=[],
    )
    doc_cache.set_package_documentation("src/auth", cached)

    package_info = {"files": ["src/auth/login.py"], "sub_packages": []}
    result = await document_package(str(tmp_path), "src/auth", package_info, mock_llm, doc_cache)

    mock_llm.generate_agent.assert_not_called()
    assert result.description == "Cached package description."


# ---------------------------------------------------------------------------
# document_package — calls LLM and caches result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_package_calls_llm_and_caches(doc_cache, mock_llm, tmp_path):
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Auth package for login flows."}, MagicMock())
    )

    package_info = {"files": ["src/auth/login.py"], "sub_packages": []}
    result = await document_package(str(tmp_path), "src/auth", package_info, mock_llm, doc_cache)

    mock_llm.generate_agent.assert_called_once()
    assert result.description == "Auth package for login flows."
    assert result.path == "src/auth"
    assert result.files == ["src/auth/login.py"]
    assert result.packages == []
    assert doc_cache.get_package_documentation("src/auth") is not None


# ---------------------------------------------------------------------------
# document_package — builds context from file docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_package_includes_file_context(doc_cache, mock_llm, tmp_path):
    file_doc = FileDoc(
        path="src/auth/login.py",
        type=FileDocType.CODE,
        description="Handles login logic.",
        items=[],
    )
    doc_cache.set_file_documentation("src/auth/login.py", file_doc)

    captured_prompts: list[str] = []

    async def mock_generate_agent(**kwargs):
        captured_prompts.append(kwargs.get("prompt", ""))
        return {"description": "Auth package."}, MagicMock()

    mock_llm.generate_agent = mock_generate_agent

    package_info = {"files": ["src/auth/login.py"], "sub_packages": []}
    await document_package(str(tmp_path), "src/auth", package_info, mock_llm, doc_cache)

    assert len(captured_prompts) == 1
    assert "Handles login logic." in captured_prompts[0]


# ---------------------------------------------------------------------------
# document_package — builds context from sub-package docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_package_includes_sub_package_context(doc_cache, mock_llm, tmp_path):
    sub_pkg_doc = PackageDoc(
        path="src/auth/providers",
        description="OAuth provider implementations.",
        files=[],
        packages=[],
    )
    doc_cache.set_package_documentation("src/auth/providers", sub_pkg_doc)

    captured_prompts: list[str] = []

    async def mock_generate_agent(**kwargs):
        captured_prompts.append(kwargs.get("prompt", ""))
        return {"description": "Auth with providers."}, MagicMock()

    mock_llm.generate_agent = mock_generate_agent

    package_info = {"files": [], "sub_packages": ["src/auth/providers"]}
    await document_package(str(tmp_path), "src/auth", package_info, mock_llm, doc_cache)

    assert "OAuth provider implementations." in captured_prompts[0]


# ---------------------------------------------------------------------------
# document_package — no file docs available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_package_no_file_docs(doc_cache, mock_llm, tmp_path):
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "A package with no documented files yet."}, MagicMock())
    )

    package_info = {"files": ["src/auth/login.py"], "sub_packages": []}
    result = await document_package(str(tmp_path), "src/auth", package_info, mock_llm, doc_cache)

    # Should still succeed, just with "No documented files." in prompt
    assert result.description == "A package with no documented files yet."


# ---------------------------------------------------------------------------
# document_package — files and sub_packages stored in result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_package_stores_files_and_packages(doc_cache, mock_llm, tmp_path):
    mock_llm.generate_agent = AsyncMock(
        return_value=({"description": "Full package."}, MagicMock())
    )

    package_info = {
        "files": ["src/utils/helpers.py", "src/utils/math.py"],
        "sub_packages": ["src/utils/strings"],
    }
    result = await document_package(str(tmp_path), "src/utils", package_info, mock_llm, doc_cache)

    assert result.files == ["src/utils/helpers.py", "src/utils/math.py"]
    assert result.packages == ["src/utils/strings"]
