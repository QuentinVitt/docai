from unittest.mock import AsyncMock, MagicMock

import pytest

from docai.deps.universal_extractor import _SYSTEM_PROMPT, extract_dependencies


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=({"dependencies": []}, None))
    return llm


@pytest.fixture
def sample_files():
    return [
        "src/main.py",
        "src/utils.py",
        "src/models/user.py",
        "src/models/post.py",
    ]


# --- Return value tests ---


@pytest.mark.asyncio
async def test_returns_dependencies(mock_llm, sample_files):
    mock_llm.generate.return_value = (
        {"dependencies": ["src/utils.py", "src/models/user.py"]},
        None,
    )

    result = await extract_dependencies(
        file="src/main.py",
        file_content="import utils\nimport models.user",
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    assert result == {"src/utils.py", "src/models/user.py"}


@pytest.mark.asyncio
async def test_returns_empty_list_when_no_dependencies(mock_llm, sample_files):
    result = await extract_dependencies(
        file="src/main.py",
        file_content="# no imports",
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    assert result == set()


@pytest.mark.asyncio
async def test_missing_dependencies_key_returns_empty_list(mock_llm, sample_files):
    """Dict response without 'dependencies' key falls back to empty list."""
    mock_llm.generate.return_value = ({"something_else": ["src/utils.py"]}, None)

    result = await extract_dependencies(
        file="src/main.py",
        file_content="",
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    assert result == set()


# --- Self-exclusion test ---


@pytest.mark.asyncio
async def test_current_file_excluded_from_project_files(mock_llm):
    current_file = "src/main.py"
    other_files = ["src/utils.py", "src/models.py"]
    all_files = [current_file] + other_files

    await extract_dependencies(
        file=current_file,
        file_content="",
        file_type="py",
        all_files=all_files,
        llm=mock_llm,
    )

    _, kwargs = mock_llm.generate.call_args
    prompt = kwargs["prompt"]
    expected_file_list = "\n".join(sorted(other_files))
    assert expected_file_list in prompt


# --- Prompt content tests ---


@pytest.mark.asyncio
async def test_prompt_contains_file_path(mock_llm, sample_files):
    await extract_dependencies(
        file="src/main.py",
        file_content="some content",
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    _, kwargs = mock_llm.generate.call_args
    assert "src/main.py" in kwargs["prompt"]


@pytest.mark.asyncio
async def test_prompt_contains_file_content(mock_llm, sample_files):
    content = "from utils import helper\nimport os"

    await extract_dependencies(
        file="src/main.py",
        file_content=content,
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    _, kwargs = mock_llm.generate.call_args
    assert content in kwargs["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_type,expected_lang",
    [
        ("py", "py"),
        ("js", "js"),
        ("ts", "ts"),
        (None, "unknown"),
    ],
)
async def test_file_type_in_prompt(mock_llm, sample_files, file_type, expected_lang):
    await extract_dependencies(
        file="src/main.py",
        file_content="",
        file_type=file_type,
        all_files=sample_files,
        llm=mock_llm,
    )

    _, kwargs = mock_llm.generate.call_args
    assert expected_lang in kwargs["prompt"]


# --- LLM call argument tests ---


@pytest.mark.asyncio
async def test_system_prompt_is_passed(mock_llm, sample_files):
    await extract_dependencies(
        file="src/main.py",
        file_content="",
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    _, kwargs = mock_llm.generate.call_args
    assert kwargs["system_prompt"] == _SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_structured_output_schema_is_correct(mock_llm, sample_files):
    await extract_dependencies(
        file="src/main.py",
        file_content="",
        file_type="py",
        all_files=sample_files,
        llm=mock_llm,
    )

    _, kwargs = mock_llm.generate.call_args
    schema = kwargs["structured_output"]

    assert schema["type"] == "object"
    assert schema["required"] == ["dependencies"]
    assert schema["properties"]["dependencies"]["type"] == "array"
    assert schema["properties"]["dependencies"]["items"] == {"type": "string"}


# --- Error handling tests ---


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", ["a string", 42, ["a", "list"], None])
async def test_raises_value_error_on_non_dict_result(mock_llm, sample_files, bad_result):
    mock_llm.generate.return_value = (bad_result, None)

    with pytest.raises(ValueError):
        await extract_dependencies(
            file="src/main.py",
            file_content="",
            file_type="py",
            all_files=sample_files,
            llm=mock_llm,
        )


@pytest.mark.asyncio
async def test_llm_exception_propagates(mock_llm, sample_files):
    mock_llm.generate.side_effect = RuntimeError("LLM failure")

    with pytest.raises(RuntimeError, match="LLM failure"):
        await extract_dependencies(
            file="src/main.py",
            file_content="",
            file_type="py",
            all_files=sample_files,
            llm=mock_llm,
        )
