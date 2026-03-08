import asyncio

from docai.documentation.datatypes import DocItemType, FileDocType
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content as read_file
from docai.scanning.project_infos import get_project_tree

file_type_map: dict[str, FileDocType] = {
    # --- Code ---
    "py": FileDocType.CODE,
    "js": FileDocType.CODE,
    "ts": FileDocType.CODE,
    "jsx": FileDocType.CODE,
    "tsx": FileDocType.CODE,
    "java": FileDocType.CODE,
    "c": FileDocType.CODE,
    "cpp": FileDocType.CODE,
    "h": FileDocType.CODE,
    "hpp": FileDocType.CODE,
    "cs": FileDocType.CODE,
    "go": FileDocType.CODE,
    "rs": FileDocType.CODE,
    "rb": FileDocType.CODE,
    "swift": FileDocType.CODE,
    "kt": FileDocType.CODE,
    "sh": FileDocType.CODE,
    "bash": FileDocType.CODE,
    "ps1": FileDocType.CODE,
    "sql": FileDocType.CODE,
    "r": FileDocType.CODE,
    "scala": FileDocType.CODE,
    "lua": FileDocType.CODE,
    "dart": FileDocType.CODE,
    "ex": FileDocType.CODE,
    "exs": FileDocType.CODE,
    "erl": FileDocType.CODE,
    "hs": FileDocType.CODE,
    "clj": FileDocType.CODE,
    "pl": FileDocType.CODE,
    # --- Config ---
    "yaml": FileDocType.CONFIG,
    "yml": FileDocType.CONFIG,
    "json": FileDocType.CONFIG,
    "toml": FileDocType.CONFIG,
    "ini": FileDocType.CONFIG,
    "cfg": FileDocType.CONFIG,
    "conf": FileDocType.CONFIG,
    "env": FileDocType.CONFIG,
    "properties": FileDocType.CONFIG,
    # --- Docs ---
    "md": FileDocType.DOCS,
    "rst": FileDocType.DOCS,
    # --- Other (human-authored data) ---
    "csv": FileDocType.OTHER,
    "tsv": FileDocType.OTHER,
    # --- Skipped (binary, generated, media, archives) ---
    "pdf": FileDocType.SKIPPED,
    "doc": FileDocType.SKIPPED,
    "docx": FileDocType.SKIPPED,
    "xls": FileDocType.SKIPPED,
    "xlsx": FileDocType.SKIPPED,
    "ppt": FileDocType.SKIPPED,
    "pptx": FileDocType.SKIPPED,
    "jpg": FileDocType.SKIPPED,
    "jpeg": FileDocType.SKIPPED,
    "png": FileDocType.SKIPPED,
    "gif": FileDocType.SKIPPED,
    "bmp": FileDocType.SKIPPED,
    "tiff": FileDocType.SKIPPED,
    "webp": FileDocType.SKIPPED,
    "mp3": FileDocType.SKIPPED,
    "wav": FileDocType.SKIPPED,
    "mp4": FileDocType.SKIPPED,
    "mov": FileDocType.SKIPPED,
    "avi": FileDocType.SKIPPED,
    "zip": FileDocType.SKIPPED,
    "tar": FileDocType.SKIPPED,
    "gz": FileDocType.SKIPPED,
    "rar": FileDocType.SKIPPED,
    "7z": FileDocType.SKIPPED,
    "pyc": FileDocType.SKIPPED,
    "class": FileDocType.SKIPPED,
    "exe": FileDocType.SKIPPED,
    "dll": FileDocType.SKIPPED,
    "so": FileDocType.SKIPPED,
    "dylib": FileDocType.SKIPPED,
    "whl": FileDocType.SKIPPED,
    "lock": FileDocType.SKIPPED,
    "log": FileDocType.SKIPPED,
}


async def create_file_documentation(file: str, file_type: str):
    # Agent tasks:
    # 1. Identify all entities in the file
    # 2. For each entity: generate documentation
    # 3. generate documentation for the file
    # Agent abilities:
    # - read files
    # - get project structure/tree
    # - get file/function/method/etc. documentation when available

    # 1. Identify doc file type
    doc_file_type = file_type_map.get(file_type)
    entities = await get_enties_in_file()
    for entity in entities:
        entity_doc = get_entity_documentation(entity)


_SYSTEM_PROMPT_CODE_ENTITIES = (
    "You are an expert code analyst. Identify all documentable top-level entities "
    "in a source file: public functions, classes, methods, datatypes, and "
    "module-level constants. Skip imports, local variables, and private helpers."
)

_SYSTEM_PROMPT_CONFIG_ENTITIES = (
    "You are an expert configuration analyst. Identify all named keys and sections "
    "in a configuration file. Top-level scalar keys are constants; keys whose value "
    "is a mapping or object grouping multiple related settings are datatypes."
)

_SYSTEM_PROMPT_DOCS_ENTITIES = (
    "You are an expert documentation analyst. Identify all sections in a "
    "documentation file by their headings, preserving the heading hierarchy."
)

_STRUCTURED_OUTPUT_CODE_ENTITIES: dict = {
    "type": "object",
    "required": ["entities"],
    "additionalProperties": False,
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["function", "method", "class", "datatype", "constant"],
                    },
                    "parent": {
                        "type": "string",
                        "description": "Containing class name for methods; omit for all other types.",
                    },
                },
            },
        }
    },
}


async def get_enties_in_file(
    file: str, doc_file_type: FileDocType | None, file_content: str, llm: LLMService
) -> list[tuple[str, DocItemType]]:
    match doc_file_type:
        case FileDocType.CODE:
            lang = file.rsplit(".", 1)[-1] if "." in file else "unknown"
            prompt = f"""\
Identify all documentable entities in the following {lang} source file.

Entity types:
- function : standalone callable, not inside a class
- method   : callable defined inside a class (set parent to the class name)
- class    : class or interface definition
- datatype : data structure type (dataclass, TypedDict, struct, enum, etc.)
- constant : module-level named constant (e.g. MAX_SIZE = 100)

Rules:
- Skip imports, local variables, and private/internal helpers (names starting with _).
- Skip ALL dunder methods (__init__, __str__, etc.) — they are handled separately
  when documenting the class itself.
- List each method separately from its class, with the parent field set to the class name.

<file>
Path: {file}
Language: {lang}
</file>

<file_content>
```{lang}
{file_content}
```
</file_content>

<examples>
Input (Python):
    MAX_RETRIES = 3

    class UserService:
        def __init__(self, db): ...
        def get_user(self, user_id: int): ...
        def _build_query(self): ...  # private — skip

    def format_name(first: str, last: str) -> str: ...

Output:
    [{{"name": "MAX_RETRIES",  "type": "constant", "parent": null}},
     {{"name": "UserService",  "type": "class",    "parent": null}},
     {{"name": "get_user",     "type": "method",   "parent": "UserService"}},
     {{"name": "format_name",  "type": "function", "parent": null}}]
</examples>
"""
            result, _ = await llm.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT_CODE_ENTITIES,
                structured_output=_STRUCTURED_OUTPUT_CODE_ENTITIES,
            )
            entities = result.get("entities", []) if isinstance(result, dict) else []
            return [
                (e["name"], DocItemType(e["type"]))
                for e in entities
                if "name" in e and "type" in e
            ]
        case FileDocType.CONFIG:
            lang = file.rsplit(".", 1)[-1] if "." in file else "unknown"
            prompt = f"""\
Identify all named keys and sections in the following {lang} configuration file.

Entity types:
- datatype : a key whose value is a mapping/object grouping multiple related settings
- constant : a key holding a scalar or list value

Rules:
- Extract top-level keys and keys nested one level inside a datatype section.
- For nested keys, set parent to the name of the enclosing section.
- Skip comments and anchor/alias definitions.

<file>
Path: {file}
Format: {lang}
</file>

<file_content>
```{lang}
{file_content}
```
</file_content>

<examples>
Input (yaml):
    database:
      host: localhost
      port: 5432
    debug: false
    allowed_hosts:
      - example.com

Output:
    [{{"name": "database",      "type": "datatype", "parent": null}},
     {{"name": "host",          "type": "constant", "parent": "database"}},
     {{"name": "port",          "type": "constant", "parent": "database"}},
     {{"name": "debug",         "type": "constant", "parent": null}},
     {{"name": "allowed_hosts", "type": "constant", "parent": null}}]
</examples>
"""
            result, _ = await llm.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT_CONFIG_ENTITIES,
                structured_output=_STRUCTURED_OUTPUT_CODE_ENTITIES,
            )
            entities = result.get("entities", []) if isinstance(result, dict) else []
            return [
                (e["name"], DocItemType(e["type"]))
                for e in entities
                if "name" in e and "type" in e
            ]

        case FileDocType.DOCS:
            prompt = f"""\
Identify all sections in the following documentation file by their headings.

Entity types:
- constant : a section or subsection identified by its heading

Rules:
- Extract every heading regardless of level.
- For subsections, set parent to the immediately enclosing parent heading.
- Use the exact heading text as the entity name (without markup like # or =).

<file>
Path: {file}
</file>

<file_content>
{file_content}
</file_content>

<examples>
Input (markdown):
    # Introduction
    ## Overview
    ## Goals
    # Installation
    ## Prerequisites

Output:
    [{{"name": "Introduction",  "type": "constant", "parent": null}},
     {{"name": "Overview",      "type": "constant", "parent": "Introduction"}},
     {{"name": "Goals",         "type": "constant", "parent": "Introduction"}},
     {{"name": "Installation",  "type": "constant", "parent": null}},
     {{"name": "Prerequisites", "type": "constant", "parent": "Installation"}}]
</examples>
"""
            result, _ = await llm.generate(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT_DOCS_ENTITIES,
                structured_output=_STRUCTURED_OUTPUT_CODE_ENTITIES,
            )
            entities = result.get("entities", []) if isinstance(result, dict) else []
            return [
                (e["name"], DocItemType(e["type"]))
                for e in entities
                if "name" in e and "type" in e
            ]

        case _:
            return []


async def get_entity_documentation(entity: str) -> str: ...
