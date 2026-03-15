import os

# Shown in the tree but never expanded — useful as structural signals
_COLLAPSE_NAMES: frozenset[str] = frozenset({".git", ".venv", ".env"})

# Never shown at all — generated noise that adds no LLM context
_SKIP_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",  # Python bytecode cache
        "node_modules",  # JS/TS dependencies
    }
)


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _should_skip(name: str) -> bool:
    return name in _SKIP_NAMES


def get_project_files(project_path: str) -> set[str]:
    result = set()
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not _is_hidden(d) and not _should_skip(d)]
        for file in files:
            if not _is_hidden(file) and not _should_skip(file):
                result.add(os.path.relpath(os.path.join(root, file), project_path))
    return result


def get_file_tree(project_path: str, path: str = "", depth: int | None = None) -> str:
    root = os.path.join(project_path, path) if path else project_path
    lines: list[str] = [path or "."]
    _build_tree(root, "", depth, 0, lines)
    return "\n".join(lines)


def _build_tree(
    abs_dir: str, prefix: str, depth: int | None, current_depth: int, lines: list[str]
) -> None:
    if depth is not None and current_depth >= depth:
        return
    try:
        entries = sorted(e for e in os.listdir(abs_dir) if not _should_skip(e))
    except PermissionError:
        return
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(prefix + connector + entry)
        full = os.path.join(abs_dir, entry)
        if os.path.isdir(full) and not _is_hidden(entry):
            extension = "    " if i == len(entries) - 1 else "│   "
            _build_tree(full, prefix + extension, depth, current_depth + 1, lines)
