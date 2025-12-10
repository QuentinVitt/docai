import pytest

from docai.scanning.file_infos import get_file_type


@pytest.mark.parametrize(
    "relative_parts",
    [
        ["non_existing.txt"],
        ["missing", "nested", "file.pdf"],
        [".hidden", "ghost.json"],
    ],
)
def test_get_file_type_file_not_found(tmp_path, relative_parts):
    """Non-existent files should raise FileNotFoundError with the full path in the message."""
    file_path = tmp_path.joinpath(*relative_parts)
    with pytest.raises(FileNotFoundError, match=f"File '{file_path}' does not exist"):
        get_file_type(file_path)


@pytest.mark.parametrize(
    "relative_parts",
    [
        ["dir_not_file"],
        ["nested.dir", "leaf"],
        [".hidden_dir"],
    ],
)
def test_get_file_type_directory_passed(tmp_path, relative_parts):
    """Passing a directory should raise FileNotFoundError for that path."""
    dir_path = tmp_path.joinpath(*relative_parts)
    dir_path.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError, match=f"File '{dir_path}' does not exist"):
        get_file_type(dir_path)


@pytest.mark.parametrize(
    "extension",
    [
        "txt",
        "md",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "csv",
        "tsv",
        "json",
        "yaml",
        "yml",
        "toml",
        "ini",
        "xml",
        "html",
        "htm",
        "jpg",
        "jpeg",
        "png",
        "gif",
        "bmp",
        "tiff",
        "webp",
        "mp3",
        "wav",
        "mp4",
        "mov",
        "avi",
        "zip",
        "tar",
        "gz",
        "rar",
        "7z",
    ],
)
def test_get_file_type_simple_extensions(tmp_path, extension):
    """
    Ensure simple extensions are returned verbatim for a range of common file types.
    """
    file_path = tmp_path / f"example.{extension}"
    file_path.write_text("data")
    assert get_file_type(file_path) == extension


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
    """
    Cover filenames and directories containing dots, multiple extensions, and hidden files.
    """
    file_path = tmp_path.joinpath(*relative_parts)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("data")
    assert get_file_type(file_path) == expected_extension


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
    """
    Files without extensions should be identified via their magic numbers.
    """
    file_path = tmp_path / "file_with_signature"
    file_path.write_bytes(content)
    assert get_file_type(file_path) == expected_extension


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
    """Files without extensions should return None even with tricky names."""
    file_path = tmp_path.joinpath(*relative_parts)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("data")
    assert get_file_type(file_path) is None
