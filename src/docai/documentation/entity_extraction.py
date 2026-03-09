import logging
from typing import Optional

from docai.documentation.datatypes import DocItemType, FileDocType
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content

logger = logging.getLogger("docai_project")

# Shared entity item schema (code + config extractors).
# parent is optional: class name for methods, enclosing section for nested config keys.
_ENTITY_ITEM_SCHEMA: dict = {
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
            "description": (
                "For methods: the containing class name. "
                "For nested config keys: the enclosing section name. "
                "Omit for all other entities."
            ),
        },
    },
}

_STRUCTURED_OUTPUT_ENTITIES: dict = {
    "type": "object",
    "required": ["entities"],
    "additionalProperties": False,
    "properties": {"entities": {"type": "array", "items": _ENTITY_ITEM_SCHEMA}},
}


def _parse_entities(raw: list[dict]) -> list[tuple[str, DocItemType, str | None]]:
    return [
        (e["name"], DocItemType(e["type"]), e.get("parent"))
        for e in raw
        if "name" in e and "type" in e
    ]


async def get_entities(
    file: str, file_info: dict, llm: Optional[LLMService]
) -> list[tuple[str, DocItemType, str | None]]:

    # Invoke special entity extractors based on file type
    match file_info.get("file_type"):
        case _:
            pass

    match file_info.get("doc_type"):
        case FileDocType.CODE:
            if not llm:
                logger.error("LLMService is required for code entities")
                raise ValueError("LLMService is required for code entities")
            return await get_entities_from_code_file(file, file_info, llm)
        case FileDocType.CONFIG:
            if not llm:
                logger.error("LLMService is required for config entities")
                raise ValueError("LLMService is required for config entities")
            return await get_entities_from_config_file(file, file_info, llm)
        case FileDocType.DOCS:
            return []
        case FileDocType.OTHER:
            return []
        case FileDocType.SKIPPED:
            return []
        case _:
            if not llm:
                logger.error("LLMService is required for unknown file type entities")
                raise ValueError(
                    "LLMService is required for unknown file type entities"
                )
            return await get_entities_from_unknown_file(file, file_info, llm)


# ---------------------------------------------------------------------------
# Code files
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_CODE_ENTITIES = (
    "You are an expert code analyst. Identify all documentable top-level entities "
    "in a source file: public functions, classes, methods, datatypes, and "
    "module-level constants. For methods, always record the containing class name "
    "in the parent field. Skip imports, local variables, and private helpers."
)


async def get_entities_from_code_file(
    file: str, file_info: dict, llm: LLMService
) -> list[tuple[str, DocItemType, str | None]]:
    lang = file_info.get("file_type", "unknown")
    prompt = f"""\
Identify all documentable entities in the following {lang} source file.

Entity types:
- function : standalone callable, not inside a class
- method   : callable defined inside a class — set parent to the class name
- class    : class or interface definition
- datatype : data structure type (dataclass, TypedDict, struct, enum, etc.)
- constant : module-level named constant (e.g. MAX_SIZE = 100)

Rules:
- Skip imports, local variables, and private/internal helpers (names starting with _).
- Skip ALL dunder methods (__init__, __str__, etc.) — they are handled separately
  when documenting the class itself.
- List each method separately from its class; always set parent to the class name.
- Leave parent unset for functions, classes, datatypes, and constants.

<file>
Path: {file}
Language: {lang}
</file>

<file_content>
```{lang}
{get_file_content(file)}
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
        structured_output=_STRUCTURED_OUTPUT_ENTITIES,
    )
    return _parse_entities(
        result.get("entities", []) if isinstance(result, dict) else []
    )


# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_CONFIG_ENTITIES = (
    "You are an expert configuration analyst. Identify all named keys and sections "
    "in a configuration file. Top-level scalar keys are constants; keys whose value "
    "is a mapping grouping related settings are datatypes. For keys nested inside a "
    "section, record the section name in the parent field."
)


async def get_entities_from_config_file(
    file: str, file_info: dict, llm: LLMService
) -> list[tuple[str, DocItemType, str | None]]:
    lang = file_info.get("file_type", "unknown")
    prompt = f"""\
Identify all named keys and sections in the following {lang} configuration file.

Entity types:
- datatype : a key whose value is a mapping/object grouping multiple related settings
- constant : a key holding a scalar or list value

Rules:
- Extract top-level keys and keys nested one level inside a datatype section.
- For nested keys, set parent to the name of the enclosing section.
- Leave parent unset for top-level keys.
- Skip comments and anchor/alias definitions.

<file>
Path: {file}
Format: {lang}
</file>

<file_content>
```{lang}
{get_file_content(file)}
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
        structured_output=_STRUCTURED_OUTPUT_ENTITIES,
    )
    return _parse_entities(
        result.get("entities", []) if isinstance(result, dict) else []
    )


# ---------------------------------------------------------------------------
# Unknown / ambiguous files
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_UNKNOWN_ENTITIES = (
    "You are an expert file analyst. First classify the file as 'code', 'config', or "
    "'other'. Then extract entities accordingly: for code files identify public functions, "
    "classes, methods, datatypes, and module-level constants — always set parent to the "
    "class name for methods; for config files identify top-level keys and named sections "
    "— set parent to the section name for nested keys; for other files return an empty "
    "entity list."
)

_STRUCTURED_OUTPUT_UNKNOWN_ENTITIES: dict = {
    "type": "object",
    "required": ["doc_type", "entities"],
    "additionalProperties": False,
    "properties": {
        "doc_type": {
            "type": "string",
            "enum": ["code", "config", "other"],
            "description": "The classified type of the file.",
        },
        "entities": {"type": "array", "items": _ENTITY_ITEM_SCHEMA},
    },
}


async def get_entities_from_unknown_file(
    file: str, file_info: dict, llm: LLMService
) -> list[tuple[str, DocItemType, str | None]]:
    file_type = file_info.get("file_type", "unknown")
    prompt = f"""\
Classify and extract entities from the following file.

Step 1 — Classify the file as one of:
- "code"   : source code (scripts, programs, modules)
- "config" : configuration (settings, environment, build definitions)
- "other"  : anything else (markup, plain text, data, etc.)

Step 2 — Extract entities based on the classification:
- If "code": extract public functions, classes, methods, datatypes, and module-level
  constants. Skip private helpers (names starting with _) and all dunder methods.
  Set parent to the class name for every method; leave it unset for all other types.
- If "config": extract top-level keys (constant) and named sections whose value is a
  mapping (datatype). Set parent to the section name for nested keys; leave it unset
  for top-level keys.
- If "other": return an empty entities list.

<file>
Path: {file}
Extension: {file_type}
</file>

<file_content>
```{file_type}
{get_file_content(file)}
```
</file_content>

<examples>
Example A — PHP template classified as code:
  doc_type: "code"
  entities: [{{"name": "render_page", "type": "function",  "parent": null}},
             {{"name": "Router",      "type": "class",     "parent": null}},
             {{"name": "dispatch",    "type": "method",    "parent": "Router"}}]

Example B — .env file classified as config:
  doc_type: "config"
  entities: [{{"name": "DATABASE_URL", "type": "constant", "parent": null}},
             {{"name": "DEBUG",        "type": "constant", "parent": null}}]

Example C — plain text file:
  doc_type: "other"
  entities: []
</examples>
"""
    result, _ = await llm.generate(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT_UNKNOWN_ENTITIES,
        structured_output=_STRUCTURED_OUTPUT_UNKNOWN_ENTITIES,
    )
    if not isinstance(result, dict):
        return []

    # Propagate the resolved doc_type back so downstream steps can use it
    resolved = result.get("doc_type")
    if resolved:
        file_info["doc_type"] = FileDocType(resolved)

    return _parse_entities(result.get("entities", []))
