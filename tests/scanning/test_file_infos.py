import os

import pytest

from docai.scanning.file_infos import get_file_content, get_file_type


# ---------------------------------------------------------------------------
# get_file_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_parts",
    [
        ["non_existing.txt"],
        ["missing", "nested", "file.pdf"],
        [".hidden", "ghost.json"],
    ],
)
def test_get_file_type_file_not_found(tmp_path, relative_parts):
    rel = os.path.join(*relative_parts)
    full = os.path.join(str(tmp_path), rel)
    with pytest.raises(FileNotFoundError, match=f"File '{full}' does not exist"):
        get_file_type(str(tmp_path), rel)


@pytest.mark.parametrize(
    "relative_parts",
    [
        ["dir_not_file"],
        ["nested.dir", "leaf"],
        [".hidden_dir"],
    ],
)
def test_get_file_type_directory_passed(tmp_path, relative_parts):
    rel = os.path.join(*relative_parts)
    (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    full = os.path.join(str(tmp_path), rel)
    with pytest.raises(FileNotFoundError, match=f"File '{full}' does not exist"):
        get_file_type(str(tmp_path), rel)


@pytest.mark.parametrize(
    "extension",
    [
        "txt", "md", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
        "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "xml", "html", "htm",
        "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp",
        "mp3", "wav", "mp4", "mov", "avi",
        "zip", "tar", "gz", "rar", "7z",
    ],
)
def test_get_file_type_simple_extensions(tmp_path, extension):
    name = f"example.{extension}"
    (tmp_path / name).write_text("data")
    assert get_file_type(str(tmp_path), name) == extension


@pytest.mark.parametrize(
    "relative_parts, expected_extension",
    [
        (["archive.tar.gz"], "gz"),
        (["report.v1.2.docx"], "docx"),
        ([".config.json"], "json"),
        (["dir.with.dot", "file.txt"], "txt"),
        (["v1.0", "data.csv"], "csv"),
        (["release-1.2.3", "build.log"], "log"),
        (["space dir", "file.name.with.many.dots.md"], "md"),
        (["multi.dots.dir", "nested.dir", "video.final.mp4"], "mp4"),
        (["UPPER", "FILE.PDF"], "PDF"),
        (["numbers.2024", "report.v2.5.xls"], "xls"),
        (["tricky..double", "a..b..c.json"], "json"),
    ],
)
def test_get_file_type_complex_paths(tmp_path, relative_parts, expected_extension):
    rel = os.path.join(*relative_parts)
    file_path = tmp_path / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("data")
    assert get_file_type(str(tmp_path), rel) == expected_extension


@pytest.mark.parametrize(
    "content, expected_extension",
    [
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "png"),
        (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj", "pdf"),
        (b"PK\x03\x04\x14\x00\x00\x00\x00\x00", "zip"),
        (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
            b"\x00\x00\x00\x00\x00\x00,\x00\x00\x00\x00"
            b"\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            "gif",
        ),
    ],
)
def test_get_file_type_magic_numbers(tmp_path, content, expected_extension):
    (tmp_path / "file_with_signature").write_bytes(content)
    assert get_file_type(str(tmp_path), "file_with_signature") == expected_extension


@pytest.mark.parametrize(
    "relative_parts",
    [
        ["README"],
        ["LICENSE"],
        ["no_extension"],
        [".env"],
        [".config"],
        [".hiddenfile"],
        ["..doublehidden"],
        ["dir.with.dots", "no_extension"],
        ["nested.dir.with.dots", "another.dir", "FILE"],
        ["space dir", "NAME"],
        ["hyphen-name"],
        ["123456"],
        ["UPPERCASE"],
        ["mixed_chars-123"],
    ],
)
def test_get_file_type_no_extension(tmp_path, relative_parts):
    rel = os.path.join(*relative_parts)
    file_path = tmp_path / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("data")
    assert get_file_type(str(tmp_path), rel) is None


# ---------------------------------------------------------------------------
# get_file_content
# ---------------------------------------------------------------------------


def test_get_file_content_returns_content(tmp_path):
    (tmp_path / "file.txt").write_text("hello world")
    assert get_file_content(str(tmp_path), "file.txt") == "hello world"


def test_get_file_content_empty_file(tmp_path):
    (tmp_path / "empty.txt").write_text("")
    assert get_file_content(str(tmp_path), "empty.txt") == ""


def test_get_file_content_multiline(tmp_path):
    content = "line1\nline2\nline3"
    (tmp_path / "multi.txt").write_text(content)
    assert get_file_content(str(tmp_path), "multi.txt") == content


def test_get_file_content_unicode(tmp_path):
    content = "héllo wörld 日本語"
    (tmp_path / "unicode.txt").write_text(content, encoding="utf-8")
    assert get_file_content(str(tmp_path), "unicode.txt") == content


def test_get_file_content_nested_path(tmp_path):
    sub = tmp_path / "sub" / "dir"
    sub.mkdir(parents=True)
    (sub / "file.py").write_text("import os")
    assert get_file_content(str(tmp_path), os.path.join("sub", "dir", "file.py")) == "import os"


def test_get_file_content_file_not_found(tmp_path):
    full = os.path.join(str(tmp_path), "missing.txt")
    with pytest.raises(FileNotFoundError, match=f"File '{full}' does not exist"):
        get_file_content(str(tmp_path), "missing.txt")


def test_get_file_content_directory_passed(tmp_path):
    (tmp_path / "adir").mkdir()
    full = os.path.join(str(tmp_path), "adir")
    with pytest.raises(FileNotFoundError, match=f"File '{full}' does not exist"):
        get_file_content(str(tmp_path), "adir")
