from __future__ import annotations

import logging
from typing import Optional

from rich.progress import Progress, TaskID

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import PackageDoc
from docai.llm.agent_tools import make_tool_registry
from docai.llm.service import LLMService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema
# ---------------------------------------------------------------------------

_SCHEMA_PACKAGE_DOC = {
    "type": "object",
    "required": ["description"],
    "additionalProperties": False,
    "properties": {"description": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _validate_package_doc(result: str | dict) -> str | None:
    if not isinstance(result, dict):
        return "Expected a JSON object."
    if not result.get("description", "").strip():
        return "Missing required field: description."
    return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYS_PACKAGE = (
    "You are an expert code documentation writer. Your task is to write a concise "
    "description for a source code package (directory). Describe the package's purpose, "
    "the functionality it groups together, and its role within the broader project. "
    "Use the provided file and sub-package documentation as your source of truth. "
    "Call tools if you need additional context."
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def document_package(
    project_path: str,
    package_path: str,
    package_info: dict,
    llm: LLMService,
    cache: DocumentationCache,
    progress: Optional[Progress] = None,
    task_id: Optional[TaskID] = None,
) -> PackageDoc:
    """Generate and cache package-level documentation.

    Returns the cached PackageDoc if one already exists, otherwise calls the LLM
    and stores the result before returning.
    """
    cached = cache.get_package_documentation(package_path)
    if cached is not None:
        logger.debug("Package %s found in cache", package_path)
        return cached

    files: list[str] = package_info.get("files", [])
    sub_packages: list[str] = package_info.get("sub_packages", [])

    # Build file context from already-cached FileDoc entries
    file_contexts: list[str] = []
    for f in files:
        file_doc = cache.get_file_documentation(f)
        if file_doc is not None and file_doc.description:
            file_contexts.append(str(file_doc))

    # Build sub-package context from already-cached PackageDoc entries
    sub_package_contexts: list[str] = []
    for sp in sub_packages:
        pkg_doc = cache.get_package_documentation(sp)
        if pkg_doc is not None:
            sub_package_contexts.append(str(pkg_doc))

    files_section = (
        "\n\n".join(file_contexts) if file_contexts else "No documented files."
    )
    sub_packages_section = (
        "\n\n".join(sub_package_contexts)
        if sub_package_contexts
        else "No sub-packages."
    )

    prompt = f"""\
Describe the following package.

<package>
Path: {package_path}
</package>

<files>
{files_section}
</files>

<sub_packages>
{sub_packages_section}
</sub_packages>

Provide a concise description of the package's purpose and role in the project. \
If you need additional context, use the available tools."""

    tool_registry = make_tool_registry(project_path, cache)

    result, _ = await llm.generate_agent(
        prompt=prompt,
        system_prompt=_SYS_PACKAGE,
        allowed_tools=set(tool_registry.keys()),
        structured_output=_SCHEMA_PACKAGE_DOC,
        response_validator=_validate_package_doc,
    )
    assert isinstance(result, dict)

    package_doc = PackageDoc(
        path=package_path,
        description=result["description"],
        files=files,
        packages=sub_packages,
    )
    cache.set_package_documentation(package_path, package_doc)
    logger.debug("Documented package %s", package_path)
    if progress is not None and task_id is not None:
        progress.advance(task_id)
    return package_doc
