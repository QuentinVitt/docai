from __future__ import annotations

import logging
from typing import Optional

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import (
    Attribute,
    DocItem,
    DocItemType,
    FileDocType,
    Parameter,
    RaisesEntry,
    ReturnValue,
)
from docai.llm.agent_tools import make_tool_registry
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schemas
# ---------------------------------------------------------------------------

# _SCHEMA_CODE_CALLABLE = {
#     "type": "object",
#     "required": ["description"],
#     "additionalProperties": False,
#     "properties": {
#         "description": {"type": "string"},
#         "parameters": {
#             "type": "array",
#             "items": {
#                 "type": "object",
#                 "required": ["name", "description"],
#                 "additionalProperties": False,
#                 "properties": {
#                     "name": {"type": "string"},
#                     "type_hint": {"type": "string"},
#                     "description": {"type": "string"},
#                 },
#             },
#         },
#         "returns": {
#             "type": "object",
#             "required": ["description"],
#             "additionalProperties": False,
#             "properties": {
#                 "type_hint": {"type": "string"},
#                 "description": {"type": "string"},
#             },
#         },
#         "raises": {
#             "type": "array",
#             "items": {
#                 "type": "object",
#                 "required": ["exception", "description"],
#                 "additionalProperties": False,
#                 "properties": {
#                     "exception": {"type": "string"},
#                     "description": {"type": "string"},
#                 },
#             },
#         },
#         "side_effects": {"type": "string"},
#     },
# }

# _SCHEMA_CODE_CLASS = {
#     "type": "object",
#     "required": ["description"],
#     "additionalProperties": False,
#     "properties": {
#         "description": {"type": "string"},
#         "attributes": {
#             "type": "array",
#             "items": {
#                 "type": "object",
#                 "required": ["name", "description"],
#                 "additionalProperties": False,
#                 "properties": {
#                     "name": {"type": "string"},
#                     "type_hint": {"type": "string"},
#                     "description": {"type": "string"},
#                 },
#             },
#         },
#         "dunder_methods": {
#             "type": "array",
#             "items": {"type": "string"},
#         },
#     },
# }

# _SCHEMA_CODE_DATATYPE = {
#     "type": "object",
#     "required": ["description"],
#     "additionalProperties": False,
#     "properties": {
#         "description": {"type": "string"},
#         "attributes": {
#             "type": "array",
#             "items": {
#                 "type": "object",
#                 "required": ["name", "description"],
#                 "additionalProperties": False,
#                 "properties": {
#                     "name": {"type": "string"},
#                     "type_hint": {"type": "string"},
#                     "description": {"type": "string"},
#                 },
#             },
#         },
#     },
# }

# _SCHEMA_CODE_CONSTANT = {
#     "type": "object",
#     "required": ["description"],
#     "additionalProperties": False,
#     "properties": {
#         "description": {"type": "string"},
#     },
# }

# _SCHEMA_CONFIG_SECTION = {
#     "type": "object",
#     "required": ["description"],
#     "additionalProperties": False,
#     "properties": {
#         "description": {"type": "string"},
#     },
# }

# _SCHEMA_CONFIG_KEY = {
#     "type": "object",
#     "required": ["description"],
#     "additionalProperties": False,
#     "properties": {
#         "description": {"type": "string"},
#         "type_hint": {"type": "string"},
#         "default": {"type": "string"},
#     },
# }


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


# def _validate_code_callable_doc(result: str | dict) -> str | None:
#     if not isinstance(result, dict):
#         return "Expected a JSON object."
#     if not result.get("description", "").strip():
#         return "Missing required field: description."
#     for p in result.get("parameters", []):
#         if not p.get("name", "").strip():
#             return "Parameter is missing 'name'."
#         if not p.get("description", "").strip():
#             return f"Parameter '{p['name']}' is missing 'description'."
#     ret = result.get("returns")
#     if ret is not None and not ret.get("description", "").strip():
#         return "Returns entry is missing 'description'."
#     for r in result.get("raises", []):
#         if not r.get("exception", "").strip():
#             return "Raises entry is missing 'exception'."
#         if not r.get("description", "").strip():
#             return f"Raises entry '{r['exception']}' is missing 'description'."
#     return None


# def _validate_code_class_doc(result: str | dict) -> str | None:
#     if not isinstance(result, dict):
#         return "Expected a JSON object."
#     if not result.get("description", "").strip():
#         return "Missing required field: description."
#     for a in result.get("attributes", []):
#         if not a.get("name", "").strip():
#             return "Attribute is missing 'name'."
#         if not a.get("description", "").strip():
#             return f"Attribute '{a['name']}' is missing 'description'."
#     return None


# def _validate_description_only(result: str | dict) -> str | None:
#     if not isinstance(result, dict):
#         return "Expected a JSON object."
#     if not result.get("description", "").strip():
#         return "Missing required field: description."
#     return None


# ---------------------------------------------------------------------------
# Dependency context builder
# ---------------------------------------------------------------------------


def _build_doc_context(
    project_path: str,
    file: str,
    file_info: dict,
    cache: DocumentationCache,
) -> str:
    deps: set[str] = file_info.get("dependencies", set())
    try:
        file_content = get_file_content(project_path, file)
    except Exception:
        file_content = ""

    sections: list[str] = []
    for dep in sorted(deps):
        file_doc = cache.get_file_documentation(dep)
        if file_doc is None:
            continue
        section_lines = [f"### {dep}", file_doc.description]
        for item in file_doc.items:
            if item.name not in file_content:
                continue
            entity_doc = cache.get_entity_documentation(
                dep, item.name, item.type, item.parent
            )
            if entity_doc is None:
                continue
            line = f"  {entity_doc.name} ({entity_doc.type.value}): {entity_doc.description}"
            if entity_doc.parameters:
                params = ", ".join(
                    f"{p.name}: {p.type_hint or 'any'}" for p in entity_doc.parameters
                )
                line += f" | params: {params}"
            if entity_doc.returns:
                hint = entity_doc.returns.type_hint or entity_doc.returns.description
                line += f" | returns: {hint}"
            section_lines.append(line)
        sections.append("\n".join(section_lines))

    return (
        "\n\n".join(sections) if sections else "No dependency documentation available."
    )


# ---------------------------------------------------------------------------
# Language helper
# ---------------------------------------------------------------------------

# _LANG_MAP = {
#     ".py": "python",
#     ".js": "javascript",
#     ".ts": "typescript",
#     ".java": "java",
#     ".go": "go",
#     ".rs": "rust",
#     ".cpp": "cpp",
#     ".c": "c",
#     ".rb": "ruby",
#     ".php": "php",
# }


# def _lang(file: str) -> str:
#     ext = f".{file.rsplit('.', 1)[-1]}" if "." in file else ""
#     return _LANG_MAP.get(ext, ext.lstrip(".") or "code")


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

# _SYS_CODE_CALLABLE = (
#     "You are an expert code documentation writer. Your task is to produce precise, "
#     "complete API documentation for a single function or method. Use the provided file "
#     "content and dependency context as your source of truth. If you need to look up how "
#     "something is used elsewhere, call the available tools. Do not invent behaviour — "
#     "document only what is evident in the code."
# )

# _SYS_CODE_CLASS = (
#     "You are an expert code documentation writer. Document the given class: its purpose, "
#     "public attributes, and which dunder methods it implements. Use the file content and "
#     "dependency context. Call tools if you need additional context."
# )

# _SYS_CODE_DATATYPE = (
#     "You are an expert code documentation writer. Document the given datatype (dataclass, "
#     "TypedDict, enum, etc.): its purpose and fields. Use the file content and dependency "
#     "context. Call tools if you need additional context."
# )

# _SYS_CODE_CONSTANT = (
#     "You are an expert code documentation writer. Document the given module-level constant: "
#     "its purpose and semantics."
# )

# _SYS_CONFIG_SECTION = (
#     "You are a configuration documentation expert. Document the given configuration section: "
#     "its purpose and what it controls."
# )

# _SYS_CONFIG_KEY = (
#     "You are a configuration documentation expert. Document the given configuration key: "
#     "its purpose, the type of value it accepts, and its effect."
# )


# ---------------------------------------------------------------------------
# Specialized documenters
# ---------------------------------------------------------------------------


# async def _document_code_callable(
#     project_path: str,
#     file: str,
#     file_info: dict,
#     entity_name: str,
#     entity_type: DocItemType,
#     entity_parent: Optional[str],
#     doc_context: str,
#     llm: LLMService,
#     tool_registry: dict,
# ) -> DocItem:
#     lang = _lang(file)
#     kind = "method" if entity_parent else "function"
#     parent_line = f"Class: {entity_parent}\n" if entity_parent else ""
#     try:
#         file_content = get_file_content(project_path, file)
#     except Exception:
#         file_content = "(unavailable)"

#     prompt = f"""\
# Document the following {kind}.

# <entity>
# Name: {entity_name}
# {parent_line}File: {file} ({lang})
# </entity>

# <file_content>
# ```{lang}
# {file_content}
# ```
# </file_content>

# <dependency_context>
# {doc_context}
# </dependency_context>

# Provide complete documentation: description, all parameters (name, type hint, description), \
# return value, any exceptions raised, and side effects if applicable.
# If you need to look up how this function is called or used elsewhere, use the available tools."""

#     result, _ = await llm.generate_agent(
#         prompt=prompt,
#         system_prompt=_SYS_CODE_CALLABLE,
#         allowed_tools=set(tool_registry.keys()),
#         structured_output=_SCHEMA_CODE_CALLABLE,
#         tools=tool_registry,
#     )
#     assert isinstance(result, dict)
#     return DocItem(
#         name=entity_name,
#         type=entity_type,
#         parent=entity_parent,
#         description=result["description"],
#         parameters=[Parameter(**p) for p in result.get("parameters", [])],
#         returns=ReturnValue(**result["returns"]) if result.get("returns") else None,
#         raises=[RaisesEntry(**r) for r in result.get("raises", [])],
#         side_effects=result.get("side_effects"),
#     )


# async def _document_code_class(
#     project_path: str,
#     file: str,
#     file_info: dict,
#     entity_name: str,
#     entity_type: DocItemType,
#     entity_parent: Optional[str],
#     doc_context: str,
#     llm: LLMService,
#     tool_registry: dict,
# ) -> DocItem:
#     lang = _lang(file)
#     try:
#         file_content = get_file_content(project_path, file)
#     except Exception:
#         file_content = "(unavailable)"

#     prompt = f"""\
# Document the following class.

# <entity>
# Name: {entity_name}
# File: {file} ({lang})
# </entity>

# <file_content>
# ```{lang}
# {file_content}
# ```
# </file_content>

# <dependency_context>
# {doc_context}
# </dependency_context>

# Provide: description, public attributes (name, type hint, description), and dunder methods \
# implemented (e.g. __init__, __repr__). If you need additional context, use the available tools."""

#     result, _ = await llm.generate_agent(
#         prompt=prompt,
#         system_prompt=_SYS_CODE_CLASS,
#         allowed_tools=set(tool_registry.keys()),
#         structured_output=_SCHEMA_CODE_CLASS,
#         tools=tool_registry,
#     )
#     assert isinstance(result, dict)
#     return DocItem(
#         name=entity_name,
#         type=entity_type,
#         parent=entity_parent,
#         description=result["description"],
#         attributes=[Attribute(**a) for a in result.get("attributes", [])],
#         dunder_methods=result.get("dunder_methods", []),
#     )


# async def _document_code_datatype(
#     project_path: str,
#     file: str,
#     file_info: dict,
#     entity_name: str,
#     entity_type: DocItemType,
#     entity_parent: Optional[str],
#     doc_context: str,
#     llm: LLMService,
#     tool_registry: dict,
# ) -> DocItem:
#     lang = _lang(file)
#     try:
#         file_content = get_file_content(project_path, file)
#     except Exception:
#         file_content = "(unavailable)"

#     prompt = f"""\
# Document the following datatype.

# <entity>
# Name: {entity_name}
# File: {file} ({lang})
# </entity>

# <file_content>
# ```{lang}
# {file_content}
# ```
# </file_content>

# <dependency_context>
# {doc_context}
# </dependency_context>

# Provide: description and all fields/attributes (name, type hint, description). \
# If you need additional context, use the available tools."""

#     result, _ = await llm.generate_agent(
#         prompt=prompt,
#         system_prompt=_SYS_CODE_DATATYPE,
#         allowed_tools=set(tool_registry.keys()),
#         structured_output=_SCHEMA_CODE_DATATYPE,
#         tools=tool_registry,
#     )
#     assert isinstance(result, dict)
#     return DocItem(
#         name=entity_name,
#         type=entity_type,
#         parent=entity_parent,
#         description=result["description"],
#         attributes=[Attribute(**a) for a in result.get("attributes", [])],
#     )


# async def _document_code_constant(
#     project_path: str,
#     file: str,
#     file_info: dict,
#     entity_name: str,
#     entity_type: DocItemType,
#     entity_parent: Optional[str],
#     doc_context: str,
#     llm: LLMService,
#     tool_registry: dict,
# ) -> DocItem:
#     lang = _lang(file)
#     try:
#         file_content = get_file_content(project_path, file)
#     except Exception:
#         file_content = "(unavailable)"

#     prompt = f"""\
# Document the following module-level constant.

# <entity>
# Name: {entity_name}
# File: {file} ({lang})
# </entity>

# <file_content>
# ```{lang}
# {file_content}
# ```
# </file_content>

# Provide a concise description of the constant's purpose and semantics."""

#     result, _ = await llm.generate_agent(
#         prompt=prompt,
#         system_prompt=_SYS_CODE_CONSTANT,
#         allowed_tools=set(tool_registry.keys()),
#         structured_output=_SCHEMA_CODE_CONSTANT,
#         tools=tool_registry,
#     )
#     assert isinstance(result, dict)
#     return DocItem(
#         name=entity_name,
#         type=entity_type,
#         parent=entity_parent,
#         description=result["description"],
#     )


# async def _document_config_section(
#     project_path: str,
#     file: str,
#     file_info: dict,
#     entity_name: str,
#     entity_type: DocItemType,
#     entity_parent: Optional[str],
#     doc_context: str,
#     llm: LLMService,
#     tool_registry: dict,
# ) -> DocItem:
#     try:
#         file_content = get_file_content(project_path, file)
#     except Exception:
#         file_content = "(unavailable)"

#     prompt = f"""\
# Document the following configuration section.

# <entity>
# Name: {entity_name}
# File: {file}
# </entity>

# <file_content>
# {file_content}
# </file_content>

# Provide a concise description of what this section controls."""

#     result, _ = await llm.generate_agent(
#         prompt=prompt,
#         system_prompt=_SYS_CONFIG_SECTION,
#         allowed_tools=set(tool_registry.keys()),
#         structured_output=_SCHEMA_CONFIG_SECTION,
#         tools=tool_registry,
#     )
#     assert isinstance(result, dict)
#     return DocItem(
#         name=entity_name,
#         type=entity_type,
#         parent=entity_parent,
#         description=result["description"],
#     )


# async def _document_config_key(
#     project_path: str,
#     file: str,
#     file_info: dict,
#     entity_name: str,
#     entity_type: DocItemType,
#     entity_parent: Optional[str],
#     doc_context: str,
#     llm: LLMService,
#     tool_registry: dict,
# ) -> DocItem:
#     try:
#         file_content = get_file_content(project_path, file)
#     except Exception:
#         file_content = "(unavailable)"

#     parent_line = f"Section: {entity_parent}\n" if entity_parent else ""
#     prompt = f"""\
# Document the following configuration key.

# <entity>
# Name: {entity_name}
# {parent_line}File: {file}
# </entity>

# <file_content>
# {file_content}
# </file_content>

# Provide: description, the type of value accepted, and the default value if one exists."""

#     result, _ = await llm.generate_agent(
#         prompt=prompt,
#         system_prompt=_SYS_CONFIG_KEY,
#         allowed_tools=set(tool_registry.keys()),
#         structured_output=_SCHEMA_CONFIG_KEY,
#         tools=tool_registry,
#     )
#     assert isinstance(result, dict)
#     description = result["description"]
#     if result.get("type_hint"):
#         description = f"[{result['type_hint']}] {description}"
#     if result.get("default") is not None:
#         description += f" (default: {result['default']})"
#     return DocItem(
#         name=entity_name,
#         type=entity_type,
#         parent=entity_parent,
#         description=description,
#     )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def document_entity(
    project_path: str,
    file: str,
    file_info: dict,
    entity_name: str,
    entity_type: DocItemType,
    entity_parent: Optional[str],
    llm: LLMService,
    cache: DocumentationCache,
) -> DocItem:
    """Document a single entity and persist it in the cache.

    Returns the cached DocItem if one already exists, otherwise calls the LLM
    and stores the result before returning.
    """
    cached = cache.get_entity_documentation(
        file, entity_name, entity_type, entity_parent
    )
    if cached is not None:
        logger.debug("Entity %s/%s found in cache", file, entity_name)
        return cached

    file_doc_type = file_info.get("file_doc_type")

    doc_context = _build_doc_context(project_path, file, file_info, cache)
    tool_registry = make_tool_registry(project_path, cache)

    kwargs = dict(
        project_path=project_path,
        file=file,
        file_info=file_info,
        entity_name=entity_name,
        entity_type=entity_type,
        entity_parent=entity_parent,
        doc_context=doc_context,
        llm=llm,
        tool_registry=tool_registry,
    )

    match file_doc_type, entity_type:
        case FileDocType.CODE, DocItemType.FUNCTION:
            doc_item = await _document_code_callable(**kwargs)
        case FileDocType.CODE, DocItemType.METHOD:
            doc_item = await _document_code_callable(**kwargs)
        case FileDocType.CODE, DocItemType.CLASS:
            doc_item = await _document_code_class(**kwargs)
        case FileDocType.CODE, DocItemType.DATATYPE:
            doc_item = await _document_code_datatype(**kwargs)
        case FileDocType.CODE, DocItemType.CONSTANT:
            doc_item = await _document_code_constant(**kwargs)
        case FileDocType.CONFIG, DocItemType.DATATYPE:
            doc_item = await _document_config_section(**kwargs)
        case FileDocType.CONFIG, DocItemType.CONSTANT:
            doc_item = await _document_config_key(**kwargs)
        case _:
            raise ValueError(
                f"Unsupported combination: file_type={file_doc_type_raw!r}, "
                f"entity_type={entity_type.value!r}"
            )

    cache.set_entity_documentation(
        file, entity_name, entity_type, entity_parent, doc_item
    )
    logger.debug("Documented entity %s/%s", file, entity_name)
    return doc_item
