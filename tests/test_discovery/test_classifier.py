from __future__ import annotations

from pathlib import Path

import pytest

from docai.discovery.classifier import classify
from docai.discovery.datatypes import FileClassification


# ── parametrize data ──────────────────────────────────────────────────────────

# (filename, magic_bytes_prefix) — content is magic + padding to ensure no
# accidental shebang match on the first line.
MAGIC_BYTES_CASES: list[tuple[str, bytes]] = [
    # Images — handled by filetype
    ("img.bin", b"\x89PNG\r\n\x1a\n"),  # PNG
    ("img2.bin", b"\xff\xd8\xff"),  # JPEG
    ("img3.bin", b"GIF87a"),  # GIF87a
    ("img4.bin", b"GIF89a"),  # GIF89a
    ("img5.bin", b"BM\x00\x00"),  # BMP
    ("img6.bin", b"RIFF\x24\x00\x00\x00WEBPVP8 "),  # WebP (realistic header)
    ("img7.bin", b"II\x2a\x00"),  # TIFF LE
    ("img8.bin", b"MM\x00\x2a"),  # TIFF BE
    (
        "img9.bin",
        b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1",
    ),  # HEIC (realistic ftyp box)
    (
        "img10.bin",
        b"\x00\x00\x00\x1cftyp" + b"heif\x00\x00\x00\x00heifmif1",
    ),  # HEIF (supplemental)
    ("img11.bin", b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1"),  # AVIF
    ("img12.bin", b"\x00\x00\x01\x00"),  # ICO
    # Documents — handled by filetype
    ("doc.bin", b"%PDF"),  # PDF
    # Archives — handled by filetype
    ("arc1.bin", b"PK\x03\x04"),  # ZIP
    (
        "arc2.bin",
        b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03",
    ),  # GZIP (realistic header)
    ("arc3.bin", b"Rar!\x1a\x07"),  # RAR
    ("arc4.bin", b"7z\xbc\xaf\x27\x1c"),  # 7Z
    # Executables / compiled
    ("bin1.bin", b"\x7fELF"),  # ELF (filetype)
    ("bin2.bin", b"\xce\xfa\xed\xfe"),  # Mach-O 32-bit LE (supplemental)
    ("bin3.bin", b"\xfe\xed\xfa\xce"),  # Mach-O 32-bit BE (supplemental)
    ("bin4.bin", b"\xcf\xfa\xed\xfe"),  # Mach-O 64-bit LE (supplemental)
    ("bin5.bin", b"\xfe\xed\xfa\xcf"),  # Mach-O 64-bit BE (supplemental)
    ("bin6.bin", b"MZ"),  # PE / Windows EXE (filetype)
    ("bin7.bin", b"\x00asm\x01\x00\x00\x00"),  # WASM (realistic with version)
    # Audio — handled by filetype
    ("aud1.bin", b"ID3"),  # MP3 with ID3 tag
    ("aud2.bin", b"OggS"),  # OGG
    ("aud3.bin", b"fLaC"),  # FLAC
    ("aud4.bin", b"RIFF\x00\x00\x00\x00WAVE"),  # WAV
    # Fonts — handled by filetype
    ("font1.bin", b"OTTO"),  # OTF
    ("font2.bin", b"wOFF\x00\x01\x00\x00"),  # WOFF (realistic header)
    ("font3.bin", b"wOF2\x00\x01\x00\x00"),  # WOFF2 (realistic header)
    # Data / databases — handled by filetype
    ("db.bin", b"SQLite format 3\x00"),  # SQLite
    # Compiled code — supplemental
    ("cls.bin", b"\xca\xfe\xba\xbe"),  # Java .class
    # OLE2 compound document — supplemental
    ("ole.bin", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),  # OLE2
]

FILENAME_MAP_PROCESSED_CASES: list[tuple[str, str]] = [
    ("Dockerfile", "dockerfile"),
    ("Makefile", "make"),
    ("Justfile", "just"),
    ("Jenkinsfile", "groovy"),
    ("Rakefile", "ruby"),
    ("Gemfile", "ruby"),
    ("Procfile", "procfile"),
    ("Vagrantfile", "ruby"),
]

FILENAME_MAP_IGNORED_CASES: list[str] = [
    "package-lock.json",
    "Cargo.lock",
    "poetry.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    ".prettierrc",
    ".eslintrc",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
]

FILENAME_MAP_DOCUMENTATION_CASES: list[str] = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
]

SHEBANG_CASES: list[tuple[str, str]] = [
    ("#!/usr/bin/env python3", "python"),
    ("#!/usr/bin/env python", "python"),
    ("#!/usr/bin/env python3.9", "python"),
    ("#!/usr/bin/python", "python"),
    ("#!/usr/bin/python3", "python"),
    ("#!/bin/bash", "bash"),
    ("#!/bin/sh", "bash"),
    ("#!/usr/bin/env bash", "bash"),
    ("#!/usr/bin/env zsh", "zsh"),
    ("#!/usr/bin/env fish", "fish"),
    ("#!/usr/bin/env node", "javascript"),
    ("#!/usr/bin/env ruby", "ruby"),
    ("#!/usr/bin/env perl", "perl"),
    ("#!/usr/bin/env php", "php"),
    ("#!/usr/bin/env Rscript", "r"),
    ("#!/usr/bin/env lua", "lua"),
    ("#!/usr/bin/env julia", "julia"),
    ("#!/usr/bin/env groovy", "groovy"),
    ("#!/usr/bin/env ts-node", "typescript"),
    ("#!/usr/bin/env deno", "typescript"),
]

EXTENSION_SOURCE_CASES: list[tuple[str, str]] = [
    # Systems
    (".py", "python"),
    (".rs", "rust"),
    (".go", "go"),
    (".c", "c"),
    (".h", "c"),
    (".cpp", "cpp"),
    (".hpp", "cpp"),
    (".cc", "cpp"),
    (".cxx", "cpp"),
    (".zig", "zig"),
    (".d", "dlang"),
    (".pas", "pascal"),
    (".f90", "fortran"),
    (".f95", "fortran"),
    # JVM
    (".java", "java"),
    (".kt", "kotlin"),
    (".kts", "kotlin"),
    (".scala", "scala"),
    (".groovy", "groovy"),
    (".gradle", "groovy"),
    (".clj", "clojure"),
    (".cljs", "clojure"),
    (".cljc", "clojure"),
    # .NET
    (".cs", "csharp"),
    (".fs", "fsharp"),
    (".fsx", "fsharp"),
    # Scripting
    (".rb", "ruby"),
    (".php", "php"),
    (".pl", "perl"),
    (".pm", "perl"),
    (".lua", "lua"),
    (".sh", "bash"),
    (".bash", "bash"),
    (".zsh", "zsh"),
    (".fish", "fish"),
    (".ps1", "powershell"),
    (".r", "r"),
    (".R", "r"),
    # Functional
    (".hs", "haskell"),
    (".lhs", "haskell"),
    (".ex", "elixir"),
    (".exs", "elixir"),
    (".erl", "erlang"),
    (".hrl", "erlang"),
    (".ml", "ocaml"),
    (".mli", "ocaml"),
    (".el", "elisp"),
    (".lisp", "lisp"),
    # Mobile / cross-platform
    (".swift", "swift"),
    (".dart", "dart"),
    (".cr", "crystal"),
    (".nim", "nim"),
    # Web
    (".js", "javascript"),
    (".jsx", "javascript"),
    (".ts", "typescript"),
    (".tsx", "typescript"),
    (".vue", "vue"),
    (".svelte", "svelte"),
    (".css", "css"),
    (".scss", "scss"),
    (".sass", "sass"),
    (".less", "less"),
    (".html", "html"),
    (".htm", "html"),
    (".xml", "xml"),
    # Other languages
    (".pyx", "cython"),
    (".mm", "objectivec"),
    (".sol", "solidity"),
    (".proto", "protobuf"),
    (".graphql", "graphql"),
    (".gql", "graphql"),
    # Config / data formats treated as processed
    (".yml", "yaml"),
    (".yaml", "yaml"),
    (".toml", "toml"),
    (".json", "json"),
    (".sql", "sql"),
    (".tf", "terraform"),
    (".hcl", "hcl"),
]

EXTENSION_DOCUMENTATION_CASES: list[str] = [
    ".md",
    ".rst",
    ".adoc",
    ".org",
    ".tex",
]

EXTENSION_IGNORED_CASES: list[str] = [
    ".lock",
    ".pyc",
    ".pyo",
    ".class",
]

EXTENSION_ASSET_IMAGE_CASES: list[str] = [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".avif",
    ".raw",
    ".cr2",
    ".nef",
    ".arw",
]

EXTENSION_ASSET_VIDEO_CASES: list[str] = [
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpeg",
    ".mpg",
    ".3gp",
]

EXTENSION_ASSET_AUDIO_CASES: list[str] = [
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".m4a",
    ".wma",
    ".opus",
]

EXTENSION_ASSET_FONT_CASES: list[str] = [
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
]

EXTENSION_ASSET_ARCHIVE_CASES: list[str] = [
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".rar",
    ".7z",
    ".xz",
]

EXTENSION_ASSET_DOCUMENT_CASES: list[str] = [
    ".pdf",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
]

EXTENSION_ASSET_COMPILED_CASES: list[str] = [
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".o",
    ".a",
    ".wasm",
    ".db",
    ".sqlite",
]


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestMagicByteDetection:
    @pytest.mark.parametrize("filename,magic", MAGIC_BYTES_CASES)
    def test_binary_format_classified_as_asset(
        self,
        tmp_path: Path,
        filename: str,
        magic: bytes,
    ) -> None:
        path = tmp_path / filename
        path.write_bytes(magic + b"\x00" * 64)
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    def test_magic_bytes_win_over_extension(
        self, tmp_path: Path
    ) -> None:
        # A .py file whose bytes are a PNG image → asset, not python/processed
        path = tmp_path / "script.py"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset


@pytest.mark.integration
class TestFilenameMap:
    @pytest.mark.parametrize("filename,expected_language", FILENAME_MAP_PROCESSED_CASES)
    def test_known_extensionless_processed_filename(
        self,
        tmp_path: Path,
        filename: str,
        expected_language: str,
    ) -> None:
        path = tmp_path / filename
        path.write_bytes(b"# content")
        language, classification = classify(path)
        assert language == expected_language
        assert classification == FileClassification.processed

    @pytest.mark.parametrize("filename", FILENAME_MAP_IGNORED_CASES)
    def test_known_ignored_filename(
        self, tmp_path: Path, filename: str
    ) -> None:
        path = tmp_path / filename
        path.write_bytes(b"# content")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.ignored

    @pytest.mark.parametrize("filename", FILENAME_MAP_DOCUMENTATION_CASES)
    def test_known_documentation_filename(
        self, tmp_path: Path, filename: str
    ) -> None:
        path = tmp_path / filename
        path.write_bytes(b"# content")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.documentation

    def test_filename_map_wins_over_shebang(
        self, tmp_path: Path
    ) -> None:
        # Dockerfile with a bash shebang → filename map wins (step 2 before step 3)
        path = tmp_path / "Dockerfile"
        path.write_bytes(b"#!/bin/bash\nFROM ubuntu\n")
        language, classification = classify(path)
        assert language == "dockerfile"
        assert classification == FileClassification.processed


@pytest.mark.integration
class TestShebangDetection:
    @pytest.mark.parametrize("shebang_line,expected_language", SHEBANG_CASES)
    def test_shebang_classified_with_correct_language(
        self,
        tmp_path: Path,
        shebang_line: str,
        expected_language: str,
    ) -> None:
        path = tmp_path / "script"
        path.write_bytes(f"{shebang_line}\necho hello\n".encode())
        language, classification = classify(path)
        assert language == expected_language
        assert classification == FileClassification.processed

    def test_unknown_shebang_interpreter_falls_through_to_unknown(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "script"
        path.write_bytes(b"#!/usr/bin/env cobol-compiler\nSTOP RUN.\n")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.unknown

    def test_shebang_wins_over_extension(
        self, tmp_path: Path
    ) -> None:
        # A .py file with a ruby shebang → shebang wins (step 3 before step 4)
        path = tmp_path / "script.py"
        path.write_bytes(b"#!/usr/bin/env ruby\nputs 'hello'\n")
        language, classification = classify(path)
        assert language == "ruby"
        assert classification == FileClassification.processed


@pytest.mark.integration
class TestExtensionMapSource:
    @pytest.mark.parametrize("ext,expected_language", EXTENSION_SOURCE_CASES)
    def test_source_extension_classified_as_processed(
        self,
        tmp_path: Path,
        ext: str,
        expected_language: str,
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"# content")
        language, classification = classify(path)
        assert language == expected_language
        assert classification == FileClassification.processed


@pytest.mark.integration
class TestExtensionMapDocumentation:
    @pytest.mark.parametrize("ext", EXTENSION_DOCUMENTATION_CASES)
    def test_documentation_extension_classified_as_documentation(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"# content")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.documentation


@pytest.mark.integration
class TestExtensionMapIgnored:
    @pytest.mark.parametrize("ext", EXTENSION_IGNORED_CASES)
    def test_ignored_extension_classified_as_ignored(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"# content")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.ignored


@pytest.mark.integration
class TestExtensionMapAssets:
    @pytest.mark.parametrize("ext", EXTENSION_ASSET_IMAGE_CASES)
    def test_image_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    @pytest.mark.parametrize("ext", EXTENSION_ASSET_VIDEO_CASES)
    def test_video_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    @pytest.mark.parametrize("ext", EXTENSION_ASSET_AUDIO_CASES)
    def test_audio_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    @pytest.mark.parametrize("ext", EXTENSION_ASSET_FONT_CASES)
    def test_font_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    @pytest.mark.parametrize("ext", EXTENSION_ASSET_ARCHIVE_CASES)
    def test_archive_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    @pytest.mark.parametrize("ext", EXTENSION_ASSET_DOCUMENT_CASES)
    def test_document_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset

    @pytest.mark.parametrize("ext", EXTENSION_ASSET_COMPILED_CASES)
    def test_compiled_extension_classified_as_asset(
        self, tmp_path: Path, ext: str
    ) -> None:
        path = tmp_path / f"file{ext}"
        path.write_bytes(b"placeholder")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.asset


@pytest.mark.integration
class TestUnknownFiles:
    def test_extensionless_file_with_no_shebang_is_unknown(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "weirdfile"
        path.write_bytes(b"some content with no shebang")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.unknown

    def test_unrecognized_extension_is_unknown(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "file.xyz"
        path.write_bytes(b"some content")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.unknown

    def test_empty_file_with_unrecognized_extension_is_unknown(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "file.xyz"
        path.write_bytes(b"")
        language, classification = classify(path)
        assert language is None
        assert classification == FileClassification.unknown


@pytest.mark.integration
class TestErrorCases:
    def test_unreadable_file_raises_os_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "secret.py"
        path.write_bytes(b"content")
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                classify(path)
        finally:
            path.chmod(0o644)
