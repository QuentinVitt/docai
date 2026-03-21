from unittest.mock import patch

import pytest

from docai.deps.base import fuzzy_search_dependencies


def _run(
    content: str,
    file: str,
    all_files: set[str],
    project_path: str = "/project",
) -> set[str]:
    with patch("docai.deps.base.get_file_content", return_value=content):
        return fuzzy_search_dependencies(project_path, file, all_files)


# ---------------------------------------------------------------------------
# Shared project file sets
# ---------------------------------------------------------------------------

# Flat: all files at root
FLAT = {"utils.py", "main.py", "config.py", "helpers.py"}

# Nested: single level of directories
NESTED = {"src/utils.py", "src/main.py", "src/config.py", "tests/test_utils.py"}

# Deep: multiple levels
DEEP = {"a/b/c/deep.py", "a/b/other.py", "a/top.py", "root.py"}

# With spaces in directory names
SPACED = {"src/my module/utils.py", "src/config.py", "main.py"}


# ---------------------------------------------------------------------------
# 1.1 End boundary — no _PATH_CHARS may follow the filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # At end of string → match
    (
        "utils.py",
        "main.py", FLAT, "/project",
        {"utils.py"},
    ),
    # Followed by extension char (e.g. utils.pyc) → no match for utils.py
    (
        "utils.pyc",
        "main.py", FLAT, "/project",
        set(),
    ),
    # Followed by space → match
    (
        "utils.py is imported",
        "main.py", FLAT, "/project",
        {"utils.py"},
    ),
    # Followed by newline → match
    (
        "utils.py\nmore text",
        "main.py", FLAT, "/project",
        {"utils.py"},
    ),
    # Followed by closing paren → match
    (
        "load(utils.py)",
        "main.py", FLAT, "/project",
        {"utils.py"},
    ),
    # Followed by comma — two files both match
    (
        "utils.py,helpers.py",
        "main.py", FLAT, "/project",
        {"utils.py", "helpers.py"},
    ),
    # Extension superset: utils.pyc does not match utils.py
    (
        "utils.pyc",
        "src/main.py", NESTED, "/project",
        set(),
    ),
])
def test_end_boundary(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# 1.2 Start boundary — preceding char must be '/' or not a _PATH_CHAR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Preceded by '/' → valid path component, match via root-relative
    (
        "src/utils.py",
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Preceded by alpha that is not '/' → part of a longer token, no match
    (
        "notutils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Preceded by digit → no match
    (
        "0utils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Preceded by dot → no match (e.g. module.utils.py)
    (
        "pkg.utils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Preceded by dash — dash is in _PATH_CHARS → no match
    (
        "-utils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Preceded by underscore — underscore is in _PATH_CHARS → no match
    (
        "_utils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Preceded by space → match (bare filename, same dir)
    (
        " utils.py",
        "src/main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Preceded by '(' → match (bare filename, same dir)
    (
        "(utils.py)",
        "src/main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # At start of content → match
    (
        "utils.py is the module",
        "src/main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Preceded by newline → match
    (
        "see:\nutils.py\n",
        "src/main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
])
def test_start_boundary(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# 2.2 Unquoted path prefix extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Root-relative: src/utils.py → match via 3.2
    (
        "src/utils.py",
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Root-relative subdirectory: tests/test_utils.py
    (
        "tests/test_utils.py",
        "src/main.py", NESTED, "/project",
        {"tests/test_utils.py"},
    ),
    # Relative with ../: ../tests/test_utils.py from src/main.py → match via 3.3
    (
        "../tests/test_utils.py",
        "src/main.py", NESTED, "/project",
        {"tests/test_utils.py"},
    ),
    # Relative with ./: ./config.py from src/main.py → match via 3.3
    (
        "./config.py",
        "src/main.py", NESTED, "/project",
        {"src/config.py"},
    ),
    # Escaped space in directory name → match
    (
        "src/my\\ module/utils.py",
        "main.py", SPACED, "/project",
        {"src/my module/utils.py"},
    ),
    # Deep root-relative: a/b/c/deep.py
    (
        "a/b/c/deep.py",
        "root.py", DEEP, "/project",
        {"a/b/c/deep.py"},
    ),
    # Relative going up two levels: ../../root.py from a/b/runner.py
    (
        "../../root.py",
        "a/b/runner.py", DEEP, "/project",
        {"root.py"},
    ),
    # Deep relative: ../../top.py from a/b/c/deep.py → a/top.py
    (
        "../../top.py",
        "a/b/c/deep.py", DEEP, "/project",
        {"a/top.py"},
    ),
    # Wrong root-relative path → no match
    (
        "src/nonexistent.py",
        "main.py", NESTED, "/project",
        set(),
    ),
    # Unquoted space in directory breaks the scan → no match
    (
        "src/my module/utils.py",
        "main.py", SPACED, "/project",
        set(),
    ),
    # Relative sibling: ../src/utils.py from tests/test_utils.py → match
    (
        "../src/utils.py",
        "tests/test_utils.py", NESTED, "/project",
        {"src/utils.py"},
    ),
])
def test_unquoted_prefix_extraction(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# 2.1 Quoted path prefix extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Bare quoted filename → same-dir match via 3.4
    (
        '"utils.py"',
        "main.py", FLAT, "/project",
        {"utils.py"},
    ),
    # Quoted root-relative path → match via 3.2
    (
        '"src/utils.py"',
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Quoted path with space in directory → match via 3.2
    (
        '"src/my module/utils.py"',
        "main.py", SPACED, "/project",
        {"src/my module/utils.py"},
    ),
    # Quoted path in YAML-like assignment: key: "src/utils.py"
    (
        'config: "src/utils.py"',
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Quoted relative path with ./
    (
        '"./config.py"',
        "src/main.py", NESTED, "/project",
        {"src/config.py"},
    ),
    # Closing quote present but no opening quote → falls through to 2.2 → match
    (
        'src/utils.py"',
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Space in path but no quotes → scan stops at space → no match
    (
        '"src/my module/utils.py',  # closing quote missing
        "main.py", SPACED, "/project",
        set(),
    ),
    # Quoted path in JSON value
    (
        '{"path": "src/utils.py"}',
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
])
def test_quoted_prefix_extraction(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# 3.1 Absolute path matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Absolute path to a root-level file → match
    (
        "/project/utils.py",
        "src/main.py", FLAT, "/project",
        {"utils.py"},
    ),
    # Absolute path to a nested file → no match (3.1 checks basename only)
    (
        "/project/src/utils.py",
        "main.py", NESTED, "/project",
        set(),
    ),
    # Absolute path from a different project root → no match
    (
        "/other/utils.py",
        "src/main.py", FLAT, "/project",
        set(),
    ),
    # Partial absolute: project path but no filename → no match
    (
        "/project/src/",
        "main.py", NESTED, "/project",
        set(),
    ),
])
def test_absolute_path_matching(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# 3.4 Filename-only matching (same directory)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Bare filename, same directory → match
    (
        "utils.py",
        "src/main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Bare filename, different directory → no match
    (
        "test_utils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Bare filename at project root → match root-level file
    (
        "helpers.py",
        "main.py", FLAT, "/project",
        {"helpers.py"},
    ),
    # Bare filename at root, target lives in a subdir → no match
    (
        "test_utils.py",
        "main.py", NESTED, "/project",
        set(),
    ),
    # Bare filename that doesn't exist in any file → no match
    (
        "phantom.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Bare filename, both current file and target at root
    (
        "config.py",
        "main.py", FLAT, "/project",
        {"config.py"},
    ),
])
def test_filename_only_same_dir(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# Multiple files and multiple occurrences
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Two root-relative paths in one content → both matched
    (
        "src/utils.py and src/config.py",
        "main.py", NESTED, "/project",
        {"src/utils.py", "src/config.py"},
    ),
    # All flat files referenced (self excluded)
    (
        "main.py utils.py config.py helpers.py",
        "main.py", FLAT, "/project",
        {"utils.py", "config.py", "helpers.py"},
    ),
    # CSV-style: two files separated by comma
    (
        "src/utils.py, src/config.py",
        "main.py", NESTED, "/project",
        {"src/utils.py", "src/config.py"},
    ),
    # First occurrence invalid (part of longer name), second valid → match
    (
        "notutils.py src/utils.py",
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Both occurrences invalid → no match
    (
        "notutils.py notutils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Markdown link: [utils.py](src/utils.py) → second occurrence (with prefix) matches
    (
        "[utils.py](src/utils.py)",
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
])
def test_multiple_files_and_occurrences(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# Real-world config and markup patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # YAML assignment: key: value
    (
        "script: src/main.py",
        "root.py", NESTED, "/project",
        {"src/main.py"},
    ),
    # Dockerfile COPY instruction
    (
        "COPY src/utils.py /app/",
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Comment reference
    (
        "# see src/config.py for details",
        "src/main.py", NESTED, "/project",
        {"src/config.py"},
    ),
    # Shell variable reference breaks prefix extraction → no match
    (
        "$(SRC)/utils.py",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Newline-separated list
    (
        "src/utils.py\nsrc/config.py\n",
        "main.py", NESTED, "/project",
        {"src/utils.py", "src/config.py"},
    ),
    # Function call style: func(config.py) — bare, same dir
    (
        "load(config.py)",
        "src/main.py", NESTED, "/project",
        {"src/config.py"},
    ),
])
def test_real_world_patterns(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content, file, all_files, project_path, expected", [
    # Empty content → no match
    (
        "",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Content with no recognisable filenames
    (
        "hello world nothing here",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Content is only whitespace/newlines
    (
        "\n\n\n",
        "src/main.py", NESTED, "/project",
        set(),
    ),
    # Content is uppercase → function lowercases it, match still found
    (
        "SRC/UTILS.PY",
        "main.py", NESTED, "/project",
        {"src/utils.py"},
    ),
    # Self-reference: file appears in its own content → excluded
    (
        "main.py",
        "main.py", FLAT, "/project",
        set(),
    ),
    # Deep file referenced from root-level file via root-relative path
    (
        "a/b/other.py",
        "root.py", DEEP, "/project",
        {"a/b/other.py"},
    ),
])
def test_edge_cases(content, file, all_files, project_path, expected):
    assert _run(content, file, all_files, project_path) == expected
