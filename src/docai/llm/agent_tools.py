# functions the agent needs:
#
# 1. `get_file_tree(path?, depth?)` — replaces both #1 and #2
# 2. `read_file(path)`
# 3. `get_documentation(path, entity_name?, entity_type?)`
# 4. `search_in_project(query, path?)`

from docai.scanning.file_infos import get_file_content as _get_file_content
from docai.scanning.project_infos import get_file_tree as _get_file_tree

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


def make_tool_registry(project_path: str) -> dict:
    def get_file_tree(path: str = "", depth: int | None = None) -> str:
        return _get_file_tree(project_path, path, depth)

    def read_file(path: str) -> str:
        return _get_file_content(project_path, path)

    # TODO: also add the 3. and 4. tool
    return {
        "get_file_tree": {
            "schema": _GET_FILE_TREE_SCHEMA,
            "callable": get_file_tree,
        },
        "read_file": {
            "schema": _READ_FILE_SCHEMA,
            "callable": read_file,
        },
    }
