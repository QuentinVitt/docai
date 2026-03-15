import os

from docai.scanning.project_infos import _is_hidden, _should_skip

# Hard cap to avoid overwhelming the LLM context window
_MAX_RESULTS = 200


def search_in_project(
    project_path: str,
    query: str,
    path: str = "",
    max_results: int = _MAX_RESULTS,
) -> tuple[list[tuple[str, int, str]], bool]:
    """Case-insensitive substring search across all text files under project_path/path.

    Returns (matches, truncated) where:
      matches   — list of (relative_path, line_number, line_content)
      truncated — True if max_results was hit before the full scan completed
    """
    search_root = os.path.join(project_path, path) if path else project_path
    results: list[tuple[str, int, str]] = []
    query_lower = query.lower()

    for root, dirs, files in os.walk(search_root):
        dirs[:] = sorted(d for d in dirs if not _is_hidden(d) and not _should_skip(d))
        for filename in sorted(files):
            if _is_hidden(filename) or _should_skip(filename):
                continue
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, project_path)
            try:
                with open(abs_path, encoding="utf-8", errors="strict") as f:
                    for line_num, line in enumerate(f, 1):
                        if query_lower in line.lower():
                            results.append((rel_path, line_num, line.rstrip()))
                            if len(results) >= max_results:
                                return results, True
            except (UnicodeDecodeError, OSError):
                continue

    return results, False
