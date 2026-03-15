# functions the agent needs:
#
# 1. `get_file_tree(path?, depth?)` — replaces both #1 and #2
# 2. `read_file(path)`
# 3. `get_documentation(path, entity_name?, entity_type?)`
# 4. `search_in_project(query, path?)`

from typing import Optional

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import DocItem, DocItemType, FileDoc
from docai.scanning.file_infos import get_file_content as _get_file_content
from docai.scanning.project_infos import get_file_tree as _get_file_tree
from docai.scanning.search import search_in_project as _search_in_project

_GET_FILE_TREE_SCHEMA = {
    "name": "get_file_tree",
    "description": "Gets the file tree of the project or a subdirectory.",
    "parameters_json_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to a subdirectory. Defaults to the project root.",
            },
            "depth": {
                "type": "integer",
                "description": "How many levels deep to show. Omit for the full tree.",
            },
        },
        "required": [],
    },
}

_READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "Reads and returns the content of a file in the project.",
    "parameters_json_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file within the project.",
            },
        },
        "required": ["path"],
    },
}

_SEARCH_IN_PROJECT_SCHEMA = {
    "name": "search_in_project",
    "description": (
        "Case-insensitive text search across all source files in the project. "
        "Returns matching lines with file paths and line numbers, like grep. "
        "Useful for finding where a symbol, function, or string is used or defined."
    ),
    "parameters_json_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The text to search for (case-insensitive substring match).",
            },
            "path": {
                "type": "string",
                "description": "Restrict the search to this subdirectory. Defaults to the project root.",
            },
        },
        "required": ["query"],
    },
}

_GET_DOCUMENTATION_SCHEMA = {
    "name": "get_documentation",
    "description": (
        "Returns generated documentation for a file or a specific entity within it. "
        "Provide only 'path' to get the file-level description and a list of all "
        "documented entities. Add 'entity_name' to look up a specific entity — fuzzy "
        "matching is used, so approximate names work. Optionally narrow results with "
        "'entity_type'."
    ),
    "parameters_json_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file within the project.",
            },
            "entity_name": {
                "type": "string",
                "description": (
                    "Name of the entity to look up (function, class, method, etc.). "
                    "Approximate names are accepted."
                ),
            },
            "entity_type": {
                "type": "string",
                "enum": ["function", "method", "class", "datatype", "constant"],
                "description": "Optional type hint to narrow the search.",
            },
        },
        "required": ["path"],
    },
}


def _format_item(item: DocItem, header_prefix: str = "") -> list[str]:
    lines = []
    parent_str = f", parent: {item.parent}" if item.parent else ""
    lines.append(f"{header_prefix}{item.name} ({item.type.value}{parent_str})")
    lines.append(f"  Description: {item.description}")
    if item.parameters:
        lines.append("  Parameters:")
        for p in item.parameters:
            type_str = f" ({p.type_hint})" if p.type_hint else ""
            lines.append(f"    - {p.name}{type_str}: {p.description}")
    if item.returns:
        type_str = f" ({item.returns.type_hint})" if item.returns.type_hint else ""
        lines.append(f"  Returns{type_str}: {item.returns.description}")
    if item.raises:
        lines.append("  Raises:")
        for r in item.raises:
            lines.append(f"    - {r.exception}: {r.description}")
    if item.side_effects:
        lines.append(f"  Side effects: {item.side_effects}")
    if item.attributes:
        lines.append("  Attributes:")
        for a in item.attributes:
            type_str = f" ({a.type_hint})" if a.type_hint else ""
            lines.append(f"    - {a.name}{type_str}: {a.description}")
    if item.dunder_methods:
        lines.append(f"  Dunder methods: {', '.join(item.dunder_methods)}")
    return lines


def _format_doc_result(
    file_path: str,
    file_doc: FileDoc | None,
    items: list[DocItem],
    entity_name: str | None,
) -> str:
    if file_doc is None:
        return f"No documentation available for '{file_path}'."

    file_header = [
        f"File: {file_doc.path} ({file_doc.type.value})",
        f"Description: {file_doc.description}",
    ]

    if entity_name is None:
        # File-level overview
        lines = file_header
        if file_doc.items:
            lines.append("\nEntities:")
            for item in file_doc.items:
                parent_str = f", parent: {item.parent}" if item.parent else ""
                lines.append(f"  - {item.name} ({item.type.value}{parent_str})")
        else:
            lines.append("\nNo entities documented.")
        return "\n".join(lines)

    if not items:
        lines = file_header + [
            f"\nNo documentation found for '{entity_name}'.",
        ]
        if file_doc.items:
            available = ", ".join(f"{i.name} ({i.type.value})" for i in file_doc.items)
            lines.append(f"Available entities: {available}")
        return "\n".join(lines)

    if len(items) == 1:
        return "\n".join(file_header + [""] + _format_item(items[0]))

    # Multiple matches — show all with numbered headers
    lines = file_header + [f"\nFound {len(items)} matches for '{entity_name}':\n"]
    for idx, item in enumerate(items, 1):
        lines.extend(_format_item(item, header_prefix=f"{idx}. "))
        if idx < len(items):
            lines.append("")
    return "\n".join(lines)


def make_tool_registry(
    project_path: str,
    documentation_cache: Optional[DocumentationCache] = None,
) -> dict:
    def get_file_tree(path: str = "", depth: int | None = None) -> str:
        return _get_file_tree(project_path, path, depth)

    def read_file(path: str) -> str:
        return _get_file_content(project_path, path)

    def get_documentation(
        path: str,
        entity_name: str | None = None,
        entity_type: str | None = None,
    ) -> str:
        if documentation_cache is None:
            return "Documentation is not available yet."
        parsed_type: DocItemType | None = None
        if entity_type:
            try:
                parsed_type = DocItemType(entity_type)
            except ValueError:
                return (
                    f"Unknown entity_type '{entity_type}'. "
                    f"Valid values: {', '.join(t.value for t in DocItemType)}."
                )
        file_doc, matched = documentation_cache.search_documentation(
            path, entity_name, parsed_type
        )
        return _format_doc_result(path, file_doc, matched, entity_name)

    def search_in_project(query: str, path: str = "") -> str:
        matches, truncated = _search_in_project(project_path, query, path)
        if not matches:
            scope = f" under '{path}'" if path else ""
            return f"No matches for '{query}'{scope}."
        lines = [
            f"Found {len(matches)}{'+' if truncated else ''} matches for '{query}':\n"
        ]
        for rel_path, line_num, content in matches:
            lines.append(f"{rel_path}:{line_num}: {content}")
        if truncated:
            lines.append(
                f"\n(Results truncated at {len(matches)}. Narrow the search with 'path'.)"
            )
        return "\n".join(lines)

    return {
        "get_file_tree": {
            "schema": _GET_FILE_TREE_SCHEMA,
            "callable": get_file_tree,
        },
        "read_file": {
            "schema": _READ_FILE_SCHEMA,
            "callable": read_file,
        },
        "get_documentation": {
            "schema": _GET_DOCUMENTATION_SCHEMA,
            "callable": get_documentation,
        },
        "search_in_project": {
            "schema": _SEARCH_IN_PROJECT_SCHEMA,
            "callable": search_in_project,
        },
    }
