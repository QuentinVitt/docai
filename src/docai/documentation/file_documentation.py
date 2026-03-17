from __future__ import annotations

import logging

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import DocItemRef, FileDoc, FileDocType
from docai.documentation.entity_documentation import _build_doc_context, _lang
from docai.llm.agent_tools import make_tool_registry
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema
# ---------------------------------------------------------------------------

_SCHEMA_FILE_DOC = {
    "type": "object",
    "required": ["description"],
    "additionalProperties": False,
    "properties": {"description": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _validate_file_doc(result: str | dict) -> str | None:
    if not isinstance(result, dict):
        return "Expected a JSON object."
    if not result.get("description", "").strip():
        return "Missing required field: description."
    return None


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SYS_CODE_FILE = (
    "You are an expert code documentation writer. Your task is to write a concise, "
    "accurate module-level description for a source code file. Describe what the module "
    "does, what it provides (exported classes, functions, constants), and its role within "
    "the project. Use the file content, entity documentation, and dependency context as "
    "your source of truth. Call tools if you need additional context."
)

_SYS_CONFIG_FILE = (
    "You are a configuration documentation expert. Your task is to write a concise "
    "description for a configuration file. Describe what the file configures, which "
    "component it belongs to, and the overall structure it defines. Use the file content "
    "and key documentation provided. Call tools if you need additional context."
)

_SYS_DOCS_FILE = (
    "You are a technical writer. Your task is to write a concise description for a "
    "documentation or data file. Describe the topic it covers, its intended audience, "
    "and what information it contains. Use the file content as your primary source."
)


# ---------------------------------------------------------------------------
# Entity context helper
# ---------------------------------------------------------------------------


def _build_entity_context(
    file: str,
    entities: list[DocItemRef],
    cache: DocumentationCache,
) -> str:
    items = [
        str(cache.get_entity_documentation(file, e))
        for e in entities
        if cache.get_entity_documentation(file, e) is not None
    ]
    return "\n\n".join(items) if items else "No entity documentation available."


# ---------------------------------------------------------------------------
# Specialized documenters
# ---------------------------------------------------------------------------


async def _document_code_file(
    project_path: str,
    file: str,
    file_info: dict,
    entities: list[DocItemRef],
    doc_context: str,
    llm: LLMService,
    tool_registry: dict,
    cache: DocumentationCache,
) -> str:
    file_type = file_info.get("file_type", "unknown")
    lang = _lang(file_type)
    file_content = get_file_content(project_path, file)
    entity_context = _build_entity_context(file, entities, cache)

    prompt = f"""\
Write a module-level description for the following source file.

<file>
Path: {file} ({lang})
</file>

<file_content>
```{lang}
{file_content}
```
</file_content>

<entity_documentation>
{entity_context}
</entity_documentation>

<dependency_context>
{doc_context}
</dependency_context>

Provide a concise description of the module's purpose and role in the project. \
If you need to understand how this file is used elsewhere, use the available tools."""

    result, _ = await llm.generate_agent(
        prompt=prompt,
        system_prompt=_SYS_CODE_FILE,
        allowed_tools=set(tool_registry.keys()),
        structured_output=_SCHEMA_FILE_DOC,
        response_validator=_validate_file_doc,
    )
    assert isinstance(result, dict)
    return result["description"]


async def _document_config_file(
    project_path: str,
    file: str,
    file_info: dict,
    entities: list[DocItemRef],
    doc_context: str,
    llm: LLMService,
    tool_registry: dict,
    cache: DocumentationCache,
) -> str:
    file_content = get_file_content(project_path, file)
    entity_context = _build_entity_context(file, entities, cache)

    prompt = f"""\
Write a description for the following configuration file.

<file>
Path: {file}
</file>

<file_content>
{file_content}
</file_content>

<key_documentation>
{entity_context}
</key_documentation>

Provide a concise description of what this file configures and its role in the project. \
If you need additional context, use the available tools."""

    result, _ = await llm.generate_agent(
        prompt=prompt,
        system_prompt=_SYS_CONFIG_FILE,
        allowed_tools=set(tool_registry.keys()),
        structured_output=_SCHEMA_FILE_DOC,
        response_validator=_validate_file_doc,
    )
    assert isinstance(result, dict)
    return result["description"]


async def _document_docs_file(
    project_path: str,
    file: str,
    file_info: dict,
    entities: list[DocItemRef],
    doc_context: str,
    llm: LLMService,
    tool_registry: dict,
    cache: DocumentationCache,
) -> str:
    file_content = get_file_content(project_path, file)

    prompt = f"""\
Write a description for the following documentation or data file.

<file>
Path: {file}
</file>

<file_content>
{file_content}
</file_content>

Provide a concise description of the topic this file covers and the information it contains."""

    result, _ = await llm.generate_agent(
        prompt=prompt,
        system_prompt=_SYS_DOCS_FILE,
        allowed_tools=set(tool_registry.keys()),
        structured_output=_SCHEMA_FILE_DOC,
        response_validator=_validate_file_doc,
    )
    assert isinstance(result, dict)
    return result["description"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def document_file(
    project_path: str,
    file: str,
    file_info: dict,
    llm: LLMService,
    cache: DocumentationCache,
) -> FileDoc:
    """Generate and cache file-level documentation.

    Returns the cached FileDoc if one already exists, otherwise calls the LLM
    and stores the result before returning.
    """
    cached = cache.get_file_documentation(file)
    if cached is not None:
        logger.debug("File %s found in cache", file)
        return cached

    file_doc_type: FileDocType | None = file_info.get("file_doc_type")
    entities: list[DocItemRef] = file_info.get("entities", [])

    doc_context = _build_doc_context(project_path, file, file_info, cache)
    tool_registry = make_tool_registry(project_path, cache)

    args = (project_path, file, file_info, entities, doc_context, llm, tool_registry, cache)

    match file_doc_type:
        case FileDocType.CODE:
            description = await _document_code_file(*args)
        case FileDocType.CONFIG:
            description = await _document_config_file(*args)
        case FileDocType.DOCS | FileDocType.OTHER:
            description = await _document_docs_file(*args)
        case FileDocType.SKIPPED | None:
            file_doc = FileDoc(
                path=file,
                type=file_doc_type or FileDocType.SKIPPED,
                description="",
                items=[],
            )
            cache.set_file_documentation(file, file_doc)
            logger.debug("Skipped documentation for file %s (type=%s)", file, file_doc_type)
            return file_doc

    file_doc = FileDoc(
        path=file,
        type=file_doc_type,
        description=description,
        items=entities,
    )
    cache.set_file_documentation(file, file_doc)
    logger.debug("Documented file %s", file)
    return file_doc
