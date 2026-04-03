"""
Extracts dependencies of a Python file by parsing its AST.
Falls back to the universal LLM extractor on SyntaxError.
"""

import ast
import os.path
from typing import Optional

from docai.llm.service import LLMService


def _resolve_module(
    module_parts: list[str],
    level: int,
    file_dir: str,
    all_files: set[str],
) -> str | None:
    """
    Resolve a (possibly relative) import to a project file path.

    level: number of leading dots (0 = absolute, 1 = '.', 2 = '..', ...)
    module_parts: dotted module name split on '.', e.g. ['utils'] or ['pkg', 'helper']
    """
    if level > 0:
        # Relative import: walk up `level` directories from file_dir
        base_parts = file_dir.split("/") if file_dir else []
        if level - 1 > len(base_parts):
            return None
        base_parts = base_parts[: len(base_parts) - (level - 1)]
        parts = base_parts + module_parts
    else:
        parts = module_parts

    if not parts:
        return None

    rel = "/".join(parts)

    # Check both module.py and module/__init__.py
    candidates = [rel + ".py", rel + "/__init__.py"]
    for candidate in candidates:
        if candidate in all_files:
            return candidate

    return None


def extract_dependencies_ast(
    file: str,
    file_content: str,
    all_files: set[str],
) -> set[str]:
    """
    Parse the Python source and collect all project-internal imports.
    Raises SyntaxError if the source cannot be parsed.
    """
    tree = ast.parse(file_content, filename=file)

    file_dir = os.path.dirname(file)
    deps: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                # Try progressively shorter prefixes:
                # 'foo.bar.baz' could be file foo/bar/baz.py or foo/bar.py etc.
                for length in range(len(parts), 0, -1):
                    resolved = _resolve_module(parts[:length], 0, file_dir, all_files)
                    if resolved and resolved != file:
                        deps.add(resolved)
                        break

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level  # number of leading dots
            module_parts = module.split(".") if module else []

            # Try the module itself
            resolved = _resolve_module(module_parts, level, file_dir, all_files)
            if resolved and resolved != file:
                deps.add(resolved)
                continue

            # Try module.name for each imported name (submodule import)
            for alias in node.names:
                if alias.name == "*":
                    continue
                resolved = _resolve_module(
                    module_parts + [alias.name], level, file_dir, all_files
                )
                if resolved and resolved != file:
                    deps.add(resolved)

    return deps


async def extract_dependencies(
    file: str,
    file_content: str,
    all_files: set[str],
    llm: Optional[LLMService] = None,
) -> set[str]:
    try:
        return extract_dependencies_ast(file, file_content, all_files)
    except SyntaxError:
        if llm is None:
            return set()
        from docai.deps.universal_extractor import extract_dependencies as llm_extract
        return await llm_extract(file, file_content, "python", all_files, llm)
