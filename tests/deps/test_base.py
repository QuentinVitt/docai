from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docai.deps.base import (
    create_dependencies_topologically_sorted,
    set_files_dependencies,
)

# ---------------------------------------------------------------------------
# create_dependencies_topologically_sorted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_files_returns_empty_list():
    result = create_dependencies_topologically_sorted({})
    assert result == []


@pytest.mark.asyncio
async def test_all_zero_dependencies_in_one_batch():
    files = {
        "a.py": {"dependencies": set()},
        "b.py": {"dependencies": set()},
        "c.py": {"dependencies": set()},
    }
    result = create_dependencies_topologically_sorted(files)
    assert len(result) == 1
    assert result[0] == {"a.py", "b.py", "c.py"}


@pytest.mark.asyncio
async def test_linear_chain():
    # a depends on b, b depends on c — c must come first
    files = {
        "a.py": {"dependencies": {"b.py"}},
        "b.py": {"dependencies": {"c.py"}},
        "c.py": {"dependencies": set()},
    }
    result = create_dependencies_topologically_sorted(files)
    assert result == [{"c.py"}, {"b.py"}, {"a.py"}]


@pytest.mark.asyncio
async def test_diamond_dependency():
    # a depends on b and c; b and c both depend on d
    files = {
        "a.py": {"dependencies": {"b.py", "c.py"}},
        "b.py": {"dependencies": {"d.py"}},
        "c.py": {"dependencies": {"d.py"}},
        "d.py": {"dependencies": set()},
    }
    result = create_dependencies_topologically_sorted(files)
    assert result[0] == {"d.py"}
    assert result[1] == {"b.py", "c.py"}
    assert result[2] == {"a.py"}


@pytest.mark.asyncio
async def test_unknown_dependencies_appended_last():
    files = {
        "a.py": {"dependencies": set()},
        "b.py": {},  # no "dependencies" key → unknown
    }
    result = create_dependencies_topologically_sorted(files)
    assert result[0] == {"a.py"}
    assert result[-1] == {"b.py"}


@pytest.mark.asyncio
async def test_only_unknown_dependencies():
    files = {
        "a.py": {},
        "b.py": {},
    }
    result = create_dependencies_topologically_sorted(files)
    assert len(result) == 1
    assert result[0] == {"a.py", "b.py"}


@pytest.mark.asyncio
async def test_cyclic_dependencies_in_unresolved_bucket():
    files = {
        "a.py": {"dependencies": {"b.py"}},
        "b.py": {"dependencies": {"a.py"}},
    }
    result = create_dependencies_topologically_sorted(files)
    assert len(result) == 1
    assert result[0] == {"a.py", "b.py"}


@pytest.mark.asyncio
async def test_unresolved_before_unknown():
    files = {
        "a.py": {"dependencies": {"b.py"}},
        "b.py": {"dependencies": {"a.py"}},  # cycle
        "c.py": {},  # unknown
    }
    result = create_dependencies_topologically_sorted(files)
    assert {"a.py", "b.py"} in result
    assert {"c.py"} in result
    # unresolved must appear before unknown
    assert result.index({"a.py", "b.py"}) < result.index({"c.py"})


@pytest.mark.asyncio
async def test_mixed_resolved_cyclic_unknown():
    files = {
        "leaf.py": {"dependencies": set()},
        "mid.py": {"dependencies": {"leaf.py"}},
        "cycle_a.py": {"dependencies": {"cycle_b.py"}},
        "cycle_b.py": {"dependencies": {"cycle_a.py"}},
        "mystery.py": {},
    }
    result = create_dependencies_topologically_sorted(files)
    assert result[0] == {"leaf.py"}
    assert result[1] == {"mid.py"}
    assert {"cycle_a.py", "cycle_b.py"} in result
    assert {"mystery.py"} in result
    assert result.index({"cycle_a.py", "cycle_b.py"}) < result.index({"mystery.py"})


# ---------------------------------------------------------------------------
# set_files_dependencies
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate = AsyncMock()
    return llm


@pytest.mark.asyncio
async def test_set_files_dependencies_populates_dict(mock_llm):
    project_files = {
        "a.py": {"file_type": "py"},
        "b.py": {"file_type": "py"},
    }

    async def fake_get_deps(file, file_info, all_files, llm):
        return file, {"a.py"} if file == "b.py" else set()

    with patch("docai.deps.base.get_dependencies_of_file", side_effect=fake_get_deps):
        await set_files_dependencies(project_files, mock_llm)

    assert project_files["a.py"]["dependencies"] == set()
    assert project_files["b.py"]["dependencies"] == {"a.py"}


@pytest.mark.asyncio
async def test_set_files_dependencies_skips_exceptions(mock_llm):
    project_files = {
        "a.py": {"file_type": "py"},
        "b.py": {"file_type": "py"},
    }

    async def fake_get_deps(file, file_info, all_files, llm):
        if file == "a.py":
            raise RuntimeError("extraction failed")
        return file, set()

    with patch("docai.deps.base.get_dependencies_of_file", side_effect=fake_get_deps):
        await set_files_dependencies(project_files, mock_llm)

    assert "dependencies" not in project_files["a.py"]
    assert project_files["b.py"]["dependencies"] == set()


@pytest.mark.asyncio
async def test_set_files_dependencies_processes_all_files(mock_llm):
    project_files = {
        "a.py": {"file_type": "py"},
        "b.py": {"file_type": "py"},
        "c.py": {"file_type": "py"},
    }
    called_with = []

    async def fake_get_deps(file, file_info, all_files, llm):
        called_with.append(file)
        return file, set()

    with patch("docai.deps.base.get_dependencies_of_file", side_effect=fake_get_deps):
        await set_files_dependencies(project_files, mock_llm)

    assert set(called_with) == {"a.py", "b.py", "c.py"}
