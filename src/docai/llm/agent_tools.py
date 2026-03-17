# functions the agent needs:
#
# 1. `get_file_tree(path?, depth?)` — browse project structure
# 2. `read_file(path)` — read raw source
# 3. `get_documentation(level, path, queries?)` — look up docs
# 4. `search_in_project(query, path?)` — grep-like text search

from typing import Optional

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import DocItemType, EntityQuery
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
        "Returns generated documentation at the requested level.\n"
        "- level='file': File description and entity index.\n"
        "- level='entity': Full documentation for specific entities in a file. "
        "Optionally pass 'queries' (list of entity filters). "
        "Each query can have 'name', 'type', and/or 'parent' — all optional. "
        "Fuzzy name matching is used. Omit queries to get all entities.\n"
        "- level='package': Package description and contents."
    ),
    "parameters_json_schema": {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["file", "entity", "package"],
                "description": "The documentation level to retrieve.",
            },
            "path": {
                "type": "string",
                "description": "Relative path to the file or package directory.",
            },
            "queries": {
                "type": "array",
                "description": (
                    "Entity filters for level='entity'. Each object can have "
                    "'name' (fuzzy matched), 'type', and/or 'parent'. "
                    "Omit to get all entities in the file."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Entity name (approximate names work).",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["function", "method", "class", "datatype", "constant"],
                            "description": "Entity type filter.",
                        },
                        "parent": {
                            "type": "string",
                            "description": "Parent class name (for methods/nested items).",
                        },
                    },
                },
            },
        },
        "required": ["level", "path"],
    },
}


def make_tool_registry(
    project_path: str,
    documentation_cache: Optional[DocumentationCache] = None,
) -> dict:
    def get_file_tree(path: str = "", depth: int | None = None) -> str:
        return _get_file_tree(project_path, path, depth)

    def read_file(path: str) -> str:
        return _get_file_content(project_path, path)

    def get_documentation(
        level: str,
        path: str,
        queries: list[dict] | None = None,
    ) -> str:
        if documentation_cache is None:
            return "Documentation is not available yet."

        if level == "package":
            doc = documentation_cache.get_package_documentation(path)
            if doc is None:
                return f"No package documentation found for '{path}'."
            return str(doc)

        if level not in ("file", "entity"):
            return f"Unknown level '{level}'. Use: file, entity, package."

        if level == "file":
            file_doc, _ = documentation_cache.search_documentation(path)
            if file_doc is None:
                return f"No documentation available for '{path}'."
            return str(file_doc)

        # level == "entity"
        parsed_queries: list[EntityQuery] | None = None
        if queries:
            parsed_queries = []
            for q in queries:
                parsed_type: DocItemType | None = None
                if "type" in q and q["type"] is not None:
                    try:
                        parsed_type = DocItemType(q["type"])
                    except ValueError:
                        return (
                            f"Unknown entity type '{q['type']}'. "
                            f"Valid: {', '.join(t.value for t in DocItemType)}."
                        )
                parsed_queries.append(
                    EntityQuery(
                        name=q.get("name"),
                        type=parsed_type,
                        parent=q.get("parent"),
                    )
                )

        file_doc, items = documentation_cache.search_documentation(
            path, queries=parsed_queries
        )
        if file_doc is None:
            return f"No documentation available for '{path}'."

        if not items:
            result = str(file_doc)
            if parsed_queries:
                names = [q.name for q in parsed_queries if q.name]
                if names:
                    result += f"\n\nNo entities found matching {', '.join(repr(n) for n in names)}."
                else:
                    result += "\n\nNo matching entities found."
            else:
                result += "\n\nNo entities documented."
            return result

        parts = [str(file_doc), ""]
        parts.append("\n---\n".join(str(item) for item in items))
        return "\n".join(parts)

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
