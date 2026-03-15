import os

import pytest

from docai.scanning.project_infos import get_file_tree, get_project_files


# ---------------------------------------------------------------------------
# get_project_files
# ---------------------------------------------------------------------------


def test_returns_relative_paths(tmp_path):
    (tmp_path / "file.py").write_text("x")
    result = get_project_files(str(tmp_path))
    assert "file.py" in result
    for path in result:
        assert not os.path.isabs(path)


def test_returns_nested_relative_paths(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file.py").write_text("x")
    result = get_project_files(str(tmp_path))
    assert "sub/file.py" in result


def test_empty_dir_returns_empty_set(tmp_path):
    assert get_project_files(str(tmp_path)) == set()


def test_excludes_hidden_files(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / ".gitignore").write_text("*.pyc")
    result = get_project_files(str(tmp_path))
    assert ".env" not in result
    assert ".gitignore" not in result


def test_excludes_hidden_dirs_and_contents(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]")
    result = get_project_files(str(tmp_path))
    assert ".git/config" not in result
    assert not any(".git" in p for p in result)


def test_excludes_skip_dirs_and_contents(tmp_path):
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "x.pyc").write_bytes(b"\x00")
    node = tmp_path / "node_modules"
    node.mkdir()
    (node / "pkg.js").write_text("module.exports={}")
    result = get_project_files(str(tmp_path))
    assert not any("__pycache__" in p for p in result)
    assert not any("node_modules" in p for p in result)


def test_includes_normal_files_mixed_tree(tmp_path):
    (tmp_path / "main.py").write_text("x")
    (tmp_path / ".env").write_text("SECRET=1")
    hidden_dir = tmp_path / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "config").write_text("[core]")
    skip_dir = tmp_path / "__pycache__"
    skip_dir.mkdir()
    (skip_dir / "main.cpython-313.pyc").write_bytes(b"\x00")
    result = get_project_files(str(tmp_path))
    assert result == {"main.py"}


def test_multiple_files_at_root(tmp_path):
    for name in ["a.py", "b.py", "c.txt"]:
        (tmp_path / name).write_text("x")
    result = get_project_files(str(tmp_path))
    assert {"a.py", "b.py", "c.txt"} == result


def test_nested_structure(tmp_path):
    src = tmp_path / "src"
    utils = src / "utils"
    utils.mkdir(parents=True)
    (src / "main.py").write_text("x")
    (utils / "helpers.py").write_text("x")
    (tmp_path / "README.md").write_text("x")
    result = get_project_files(str(tmp_path))
    assert result == {"src/main.py", "src/utils/helpers.py", "README.md"}


# ---------------------------------------------------------------------------
# get_file_tree — structure and connectors
# ---------------------------------------------------------------------------


def test_root_label_is_dot_by_default(tmp_path):
    (tmp_path / "a.py").write_text("x")
    lines = get_file_tree(str(tmp_path)).splitlines()
    assert lines[0] == "."


def test_root_label_uses_path_arg(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("x")
    lines = get_file_tree(str(tmp_path), path="src").splitlines()
    assert lines[0] == "src"


def test_empty_project_returns_dot_only(tmp_path):
    assert get_file_tree(str(tmp_path)) == "."


def test_single_file_uses_corner_connector(tmp_path):
    (tmp_path / "a.py").write_text("x")
    output = get_file_tree(str(tmp_path))
    assert "└── a.py" in output


def test_multiple_files_last_uses_corner(tmp_path):
    for name in ["a.py", "b.py"]:
        (tmp_path / name).write_text("x")
    output = get_file_tree(str(tmp_path))
    assert "├── a.py" in output
    assert "└── b.py" in output


def test_entries_sorted_alphabetically(tmp_path):
    for name in ["c.py", "a.py", "b.py"]:
        (tmp_path / name).write_text("x")
    lines = get_file_tree(str(tmp_path)).splitlines()[1:]  # skip root "."
    names = [l.split("── ")[1] for l in lines]
    assert names == ["a.py", "b.py", "c.py"]


def test_nested_prefix_non_last_parent(tmp_path):
    for d in ["dir1", "dir2"]:
        sub = tmp_path / d
        sub.mkdir()
        (sub / "file.py").write_text("x")
    output = get_file_tree(str(tmp_path))
    # dir1 is not the last entry, so its children should use "│   " prefix
    assert "│   └── file.py" in output


def test_nested_prefix_last_parent(tmp_path):
    sub = tmp_path / "dir1"
    sub.mkdir()
    (sub / "file.py").write_text("x")
    output = get_file_tree(str(tmp_path))
    # dir1 is the only (last) entry, so its children use "    " prefix
    assert "    └── file.py" in output


def test_empty_subdir_shows_dir_no_children(tmp_path):
    (tmp_path / "emptydir").mkdir()
    output = get_file_tree(str(tmp_path))
    assert "└── emptydir" in output
    lines = output.splitlines()
    assert len(lines) == 2  # "." and "└── emptydir"


def test_path_arg_starts_tree_at_subdir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("x")
    output = get_file_tree(str(tmp_path), path="src")
    lines = output.splitlines()
    assert lines[0] == "src"
    assert "└── main.py" in output


# ---------------------------------------------------------------------------
# get_file_tree — hidden and skip filtering
# ---------------------------------------------------------------------------


def test_hidden_file_shown_in_tree(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1")
    output = get_file_tree(str(tmp_path))
    assert ".env" in output


def test_hidden_dir_shown_but_not_expanded(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]")
    output = get_file_tree(str(tmp_path))
    assert ".git" in output
    assert "config" not in output


def test_skip_dirs_not_shown(tmp_path):
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "x.pyc").write_bytes(b"\x00")
    node = tmp_path / "node_modules"
    node.mkdir()
    (node / "pkg.js").write_text("x")
    output = get_file_tree(str(tmp_path))
    assert "__pycache__" not in output
    assert "node_modules" not in output


# ---------------------------------------------------------------------------
# get_file_tree — depth limiting
# ---------------------------------------------------------------------------


def test_depth_none_shows_all_levels(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "file.py").write_text("x")
    output = get_file_tree(str(tmp_path))
    assert "file.py" in output


def test_depth_zero_shows_only_root(tmp_path):
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "file.py").write_text("x")
    output = get_file_tree(str(tmp_path), depth=0)
    assert output == "."


def test_depth_one_shows_direct_children_only(tmp_path):
    sub = tmp_path / "dir" / "sub"
    sub.mkdir(parents=True)
    (sub / "file.py").write_text("x")
    output = get_file_tree(str(tmp_path), depth=1)
    assert "dir" in output
    assert "sub" not in output


def test_depth_two_shows_two_levels(tmp_path):
    sub = tmp_path / "dir" / "sub"
    sub.mkdir(parents=True)
    (sub / "file.py").write_text("x")
    output = get_file_tree(str(tmp_path), depth=2)
    assert "sub" in output
    assert "file.py" not in output


# ---------------------------------------------------------------------------
# get_file_tree — error handling
# ---------------------------------------------------------------------------


def test_permission_error_dir_skipped(tmp_path, monkeypatch):
    sub = tmp_path / "protected"
    sub.mkdir()
    (sub / "secret.py").write_text("x")
    (tmp_path / "normal.py").write_text("x")

    real_listdir = os.listdir

    def _listdir(path):
        if os.path.abspath(path) == os.path.abspath(str(sub)):
            raise PermissionError("permission denied")
        return real_listdir(path)

    monkeypatch.setattr(os, "listdir", _listdir)

    # should not raise; protected dir appears as leaf node only
    output = get_file_tree(str(tmp_path))
    assert "protected" in output
    assert "secret.py" not in output
    assert "normal.py" in output
