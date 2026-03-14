import os


def get_project_files(project_path: str) -> set[str]:
    # create a set of all files in the project
    return {
        os.path.join(root, file)
        for root, _, files in os.walk(project_path)
        for file in files
    }


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
        entries = sorted(os.listdir(abs_dir))
    except PermissionError:
        return
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        lines.append(prefix + connector + entry)
        full = os.path.join(abs_dir, entry)
        if os.path.isdir(full):
            extension = "    " if i == len(entries) - 1 else "│   "
            _build_tree(full, prefix + extension, depth, current_depth + 1, lines)
