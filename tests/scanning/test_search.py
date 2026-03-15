import os

import pytest

from docai.scanning.search import search_in_project


# ---------------------------------------------------------------------------
# Normal behaviour
# ---------------------------------------------------------------------------


def test_finds_match(tmp_path):
    (tmp_path / "file.py").write_text("hello\n")
    matches, _ = search_in_project(str(tmp_path), "hello")
    assert ("file.py", 1, "hello") in matches


def test_case_insensitive(tmp_path):
    (tmp_path / "file.py").write_text("HELLO\n")
    matches, _ = search_in_project(str(tmp_path), "hello")
    assert len(matches) == 1
    assert matches[0][2] == "HELLO"


def test_returns_relative_paths(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file.py").write_text("hello\n")
    matches, _ = search_in_project(str(tmp_path), "hello")
    assert len(matches) == 1
    path = matches[0][0]
    assert not os.path.isabs(path)
    assert path == os.path.join("sub", "file.py")


def test_correct_line_numbers(tmp_path):
    (tmp_path / "file.py").write_text("line one\nline two\nfind me\n")
    matches, _ = search_in_project(str(tmp_path), "find me")
    assert len(matches) == 1
    assert matches[0][1] == 3


def test_multiple_matches_in_file(tmp_path):
    (tmp_path / "file.py").write_text("alpha\nbeta\nalpha again\n")
    matches, _ = search_in_project(str(tmp_path), "alpha")
    assert len(matches) == 2
    assert matches[0][1] == 1
    assert matches[1][1] == 3


def test_matches_across_files(tmp_path):
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "b.py").write_text("target\n")
    matches, _ = search_in_project(str(tmp_path), "target")
    paths = {m[0] for m in matches}
    assert "a.py" in paths
    assert "b.py" in paths


def test_path_scoping(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (src / "a.py").write_text("needle\n")
    (other / "b.py").write_text("needle\n")
    matches, _ = search_in_project(str(tmp_path), "needle", path="src")
    paths = {m[0] for m in matches}
    assert all("src" in p for p in paths)
    assert not any("other" in p for p in paths)


def test_returns_false_when_not_truncated(tmp_path):
    (tmp_path / "file.py").write_text("x\nx\nx\n")
    _, truncated = search_in_project(str(tmp_path), "x")
    assert truncated is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_no_files_returns_empty(tmp_path):
    matches, truncated = search_in_project(str(tmp_path), "anything")
    assert matches == []
    assert truncated is False


def test_no_matches_returns_empty(tmp_path):
    (tmp_path / "file.py").write_text("nothing relevant\n")
    matches, truncated = search_in_project(str(tmp_path), "xyz_not_here")
    assert matches == []
    assert truncated is False


def test_hidden_files_excluded(tmp_path):
    (tmp_path / ".secret.py").write_text("needle\n")
    matches, _ = search_in_project(str(tmp_path), "needle")
    assert matches == []


def test_hidden_dirs_excluded(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("needle\n")
    matches, _ = search_in_project(str(tmp_path), "needle")
    assert matches == []


def test_skip_dirs_excluded(tmp_path):
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "x.pyc").write_bytes(b"needle")
    matches, _ = search_in_project(str(tmp_path), "needle")
    assert matches == []


def test_binary_file_skipped(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"\x00\xff\xfe binary content")
    # Should not raise, binary files are silently skipped
    matches, truncated = search_in_project(str(tmp_path), "binary")
    assert isinstance(matches, list)


def test_max_results_truncation(tmp_path):
    (tmp_path / "file.py").write_text("x\nx\nx\nx\n")
    matches, truncated = search_in_project(str(tmp_path), "x", max_results=3)
    assert len(matches) == 3
    assert truncated is True


def test_line_content_stripped(tmp_path):
    (tmp_path / "file.py").write_text("hello\n")
    matches, _ = search_in_project(str(tmp_path), "hello")
    assert matches[0][2] == "hello"  # no trailing newline


def test_empty_query_matches_every_line(tmp_path):
    (tmp_path / "file.py").write_text("line one\nline two\nline three\n")
    matches, _ = search_in_project(str(tmp_path), "")
    assert len(matches) == 3
