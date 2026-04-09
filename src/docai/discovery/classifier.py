from __future__ import annotations

import re
from pathlib import Path

import filetype

from docai.discovery.datatypes import FileClassification

_P = FileClassification.processed
_D = FileClassification.documentation
_A = FileClassification.asset
_I = FileClassification.ignored

# ── Step 1: supplemental magic byte table ─────────────────────────────────────
# Used only for formats the `filetype` library does not cover.
# Each entry is (signature, offset, secondary_signature, secondary_offset).
# All produce (None, asset).

SUPPLEMENTAL_MAGIC: list[tuple[bytes, int, bytes | None, int | None]] = [
    # Mach-O executables / dylibs (not supported by filetype)
    (b"\xce\xfa\xed\xfe", 0, None, None),              # Mach-O 32-bit LE
    (b"\xfe\xed\xfa\xce", 0, None, None),              # Mach-O 32-bit BE
    (b"\xcf\xfa\xed\xfe", 0, None, None),              # Mach-O 64-bit LE
    (b"\xfe\xed\xfa\xcf", 0, None, None),              # Mach-O 64-bit BE
    # Java bytecode (not supported by filetype)
    (b"\xca\xfe\xba\xbe", 0, None, None),              # Java .class
    # OLE2 compound document — covers legacy .doc/.xls/.ppt
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, None, None),
    # HEIF (filetype only supports heic/avif brands, not heif)
    (b"ftyp", 4, b"heif", 8),
]

# ── Step 2: filename map ───────────────────────────────────────────────────────
# Keyed by exact path.name (case-sensitive).

FILENAME_MAP: dict[str, tuple[str | None, FileClassification]] = {
    # Processed — build / container / task runners
    "Dockerfile":   ("dockerfile", _P),
    "Makefile":     ("make",       _P),
    "Justfile":     ("just",       _P),
    "Jenkinsfile":  ("groovy",     _P),
    "Rakefile":     ("ruby",       _P),
    "Gemfile":      ("ruby",       _P),
    "Procfile":     ("procfile",   _P),
    "Vagrantfile":  ("ruby",       _P),
    # Ignored — lockfiles
    "package-lock.json": (None, _I),
    "Cargo.lock":        (None, _I),
    "poetry.lock":       (None, _I),
    "yarn.lock":         (None, _I),
    "pnpm-lock.yaml":    (None, _I),
    # Ignored — tool config boilerplate
    ".prettierrc":    (None, _I),
    ".eslintrc":      (None, _I),
    ".editorconfig":  (None, _I),
    ".gitignore":     (None, _I),
    ".gitattributes": (None, _I),
    # Documentation
    "README.md":       (None, _D),
    "CONTRIBUTING.md": (None, _D),
    "CHANGELOG.md":    (None, _D),
}

# ── Step 3: shebang interpreter map ───────────────────────────────────────────
# Keyed by bare interpreter name. Lookup tries the exact name first, then
# strips trailing version numbers (e.g. "python3.9" → "python", "lua5.4" →
# "lua") so versioned interpreters are matched without explicit map entries.

SHEBANG_MAP: dict[str, tuple[str, FileClassification]] = {
    "python":  ("python",     _P),
    "python3": ("python",     _P),
    "bash":    ("bash",       _P),
    "sh":      ("bash",       _P),
    "zsh":     ("zsh",        _P),
    "fish":    ("fish",       _P),
    "node":    ("javascript", _P),
    "nodejs":  ("javascript", _P),
    "ruby":    ("ruby",       _P),
    "perl":    ("perl",       _P),
    "perl5":   ("perl",       _P),
    "php":     ("php",        _P),
    "Rscript": ("r",          _P),
    "lua":     ("lua",        _P),
    "julia":   ("julia",      _P),
    "groovy":  ("groovy",     _P),
    "ts-node": ("typescript", _P),
    "deno":    ("typescript", _P),
}

# ── Step 4: extension map ──────────────────────────────────────────────────────
# Keyed by path.suffix (includes leading dot, case-sensitive).

EXTENSION_MAP: dict[str, tuple[str | None, FileClassification]] = {
    # ── Processed: source languages ───────────────────────────────────────────
    # Systems
    ".py":      ("python",      _P),
    ".rs":      ("rust",        _P),
    ".go":      ("go",          _P),
    ".c":       ("c",           _P),
    ".h":       ("c",           _P),
    ".cpp":     ("cpp",         _P),
    ".hpp":     ("cpp",         _P),
    ".cc":      ("cpp",         _P),
    ".cxx":     ("cpp",         _P),
    ".zig":     ("zig",         _P),
    ".d":       ("dlang",       _P),
    ".pas":     ("pascal",      _P),
    ".f90":     ("fortran",     _P),
    ".f95":     ("fortran",     _P),
    # JVM
    ".java":    ("java",        _P),
    ".kt":      ("kotlin",      _P),
    ".kts":     ("kotlin",      _P),
    ".scala":   ("scala",       _P),
    ".groovy":  ("groovy",      _P),
    ".gradle":  ("groovy",      _P),
    ".clj":     ("clojure",     _P),
    ".cljs":    ("clojure",     _P),
    ".cljc":    ("clojure",     _P),
    # .NET
    ".cs":      ("csharp",      _P),
    ".fs":      ("fsharp",      _P),
    ".fsx":     ("fsharp",      _P),
    # Scripting
    ".rb":      ("ruby",        _P),
    ".php":     ("php",         _P),
    ".pl":      ("perl",        _P),
    ".pm":      ("perl",        _P),
    ".lua":     ("lua",         _P),
    ".sh":      ("bash",        _P),
    ".bash":    ("bash",        _P),
    ".zsh":     ("zsh",         _P),
    ".fish":    ("fish",        _P),
    ".ps1":     ("powershell",  _P),
    ".r":       ("r",           _P),
    ".R":       ("r",           _P),
    # Functional
    ".hs":      ("haskell",     _P),
    ".lhs":     ("haskell",     _P),
    ".ex":      ("elixir",      _P),
    ".exs":     ("elixir",      _P),
    ".erl":     ("erlang",      _P),
    ".hrl":     ("erlang",      _P),
    ".ml":      ("ocaml",       _P),
    ".mli":     ("ocaml",       _P),
    ".el":      ("elisp",       _P),
    ".lisp":    ("lisp",        _P),
    # Mobile / cross-platform
    ".swift":   ("swift",       _P),
    ".dart":    ("dart",        _P),
    ".cr":      ("crystal",     _P),
    ".nim":     ("nim",         _P),
    # Web
    ".js":      ("javascript",  _P),
    ".jsx":     ("javascript",  _P),
    ".ts":      ("typescript",  _P),
    ".tsx":     ("typescript",  _P),
    ".vue":     ("vue",         _P),
    ".svelte":  ("svelte",      _P),
    ".css":     ("css",         _P),
    ".scss":    ("scss",        _P),
    ".sass":    ("sass",        _P),
    ".less":    ("less",        _P),
    ".html":    ("html",        _P),
    ".htm":     ("html",        _P),
    ".xml":     ("xml",         _P),
    # Other languages
    ".pyx":     ("cython",      _P),
    ".mm":      ("objectivec",  _P),
    ".sol":     ("solidity",    _P),
    ".proto":   ("protobuf",    _P),
    ".graphql": ("graphql",     _P),
    ".gql":     ("graphql",     _P),
    # ── Processed: config / data formats ──────────────────────────────────────
    ".yml":     ("yaml",        _P),
    ".yaml":    ("yaml",        _P),
    ".toml":    ("toml",        _P),
    ".json":    ("json",        _P),
    ".sql":     ("sql",         _P),
    ".tf":      ("terraform",   _P),
    ".hcl":     ("hcl",         _P),
    # ── Documentation ─────────────────────────────────────────────────────────
    ".md":      (None, _D),
    ".rst":     (None, _D),
    ".adoc":    (None, _D),
    ".org":     (None, _D),
    ".tex":     (None, _D),
    # ── Ignored ───────────────────────────────────────────────────────────────
    ".lock":    (None, _I),
    ".pyc":     (None, _I),
    ".pyo":     (None, _I),
    ".class":   (None, _I),
    # ── Asset: images ─────────────────────────────────────────────────────────
    ".png":     (None, _A),
    ".jpg":     (None, _A),
    ".jpeg":    (None, _A),
    ".gif":     (None, _A),
    ".bmp":     (None, _A),
    ".ico":     (None, _A),
    ".svg":     (None, _A),
    ".webp":    (None, _A),
    ".tiff":    (None, _A),
    ".tif":     (None, _A),
    ".heic":    (None, _A),
    ".heif":    (None, _A),
    ".avif":    (None, _A),
    ".raw":     (None, _A),
    ".cr2":     (None, _A),
    ".nef":     (None, _A),
    ".arw":     (None, _A),
    # ── Asset: video ──────────────────────────────────────────────────────────
    ".mp4":     (None, _A),
    ".avi":     (None, _A),
    ".mov":     (None, _A),
    ".mkv":     (None, _A),
    ".wmv":     (None, _A),
    ".flv":     (None, _A),
    ".webm":    (None, _A),
    ".m4v":     (None, _A),
    ".mpeg":    (None, _A),
    ".mpg":     (None, _A),
    ".3gp":     (None, _A),
    # ── Asset: audio ──────────────────────────────────────────────────────────
    ".mp3":     (None, _A),
    ".wav":     (None, _A),
    ".flac":    (None, _A),
    ".aac":     (None, _A),
    ".ogg":     (None, _A),
    ".m4a":     (None, _A),
    ".wma":     (None, _A),
    ".opus":    (None, _A),
    # ── Asset: fonts ──────────────────────────────────────────────────────────
    ".ttf":     (None, _A),
    ".otf":     (None, _A),
    ".woff":    (None, _A),
    ".woff2":   (None, _A),
    ".eot":     (None, _A),
    # ── Asset: archives ───────────────────────────────────────────────────────
    ".zip":     (None, _A),
    ".tar":     (None, _A),
    ".gz":      (None, _A),
    ".bz2":     (None, _A),
    ".rar":     (None, _A),
    ".7z":      (None, _A),
    ".xz":      (None, _A),
    # ── Asset: documents ──────────────────────────────────────────────────────
    ".pdf":     (None, _A),
    ".xls":     (None, _A),
    ".xlsx":    (None, _A),
    ".doc":     (None, _A),
    ".docx":    (None, _A),
    ".ppt":     (None, _A),
    ".pptx":    (None, _A),
    # ── Asset: compiled / data ────────────────────────────────────────────────
    ".exe":     (None, _A),
    ".dll":     (None, _A),
    ".so":      (None, _A),
    ".dylib":   (None, _A),
    ".o":       (None, _A),
    ".a":       (None, _A),
    ".wasm":    (None, _A),
    ".db":      (None, _A),
    ".sqlite":  (None, _A),
}


# ── Detection logic ────────────────────────────────────────────────────────────


def classify(path: Path) -> tuple[str | None, FileClassification]:
    """Classify a file using the four-step detection stack.

    Raises:
        OSError: if the file cannot be opened or read.
    """
    with path.open("rb") as f:
        data = f.read(512)

    # Step 1: magic bytes — filetype library first, supplemental table second
    if filetype.guess(data) is not None:
        return None, FileClassification.asset
    for sig, offset, sec_sig, sec_offset in SUPPLEMENTAL_MAGIC:
        end = offset + len(sig)
        if len(data) >= end and data[offset:end] == sig:
            if sec_sig is None:
                return None, FileClassification.asset
            sec_end = sec_offset + len(sec_sig)  # type: ignore[operator]
            if len(data) >= sec_end and data[sec_offset:sec_end] == sec_sig:
                return None, FileClassification.asset

    # Step 2: filename map
    if path.name in FILENAME_MAP:
        return FILENAME_MAP[path.name]

    # Step 3: shebang — exact match, then version-stripped fallback
    if data.startswith(b"#!"):
        interpreter = _parse_shebang(data)
        if interpreter in SHEBANG_MAP:
            return SHEBANG_MAP[interpreter]
        normalized = re.sub(r"\d+(\.\d+)*$", "", interpreter)
        if normalized and normalized in SHEBANG_MAP:
            return SHEBANG_MAP[normalized]

    # Step 4: extension map
    if path.suffix in EXTENSION_MAP:
        return EXTENSION_MAP[path.suffix]

    # Step 5: unknown fallback
    return None, FileClassification.unknown


def _parse_shebang(data: bytes) -> str:
    """Extract the interpreter name from a shebang line.

    Returns the bare interpreter name (e.g. "python3", "bash", "ts-node").
    Returns an empty string if the shebang is malformed.
    """
    first_line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace")
    parts = first_line[2:].strip().split()
    if not parts:
        return ""
    interpreter_path = parts[0]
    # #!/usr/bin/env python3  →  take the next token after env
    if interpreter_path.endswith("/env") and len(parts) > 1:
        return parts[1]
    # #!/bin/bash  →  take the last path component
    return interpreter_path.rsplit("/", 1)[-1]
