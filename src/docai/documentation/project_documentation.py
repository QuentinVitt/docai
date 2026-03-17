from __future__ import annotations

import logging

from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import ProjectDoc
from docai.llm.agent_tools import make_tool_registry
from docai.llm.service import LLMService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schema
# ---------------------------------------------------------------------------

_SCHEMA_PROJECT_DOC = {
    "type": "object",
    "required": ["description"],
    "additionalProperties": False,
    "properties": {"description": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _validate_project_doc(result: str | dict) -> str | None:
    if not isinstance(result, dict):
        return "Expected a JSON object."
    if not result.get("description", "").strip():
        return "Missing required field: description."
    return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYS_PROJECT = (
    "You are an expert technical writer. Your task is to write a concise, high-level "
    "description for an entire software project. Describe what the project does, its "
    "primary purpose, and the main areas of functionality it covers. Use the provided "
    "package documentation as your source of truth. Call tools if you need additional "
    "context."
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def document_project(
    project_path: str,
    project_name: str,
    top_level_packages: list[str],
    llm: LLMService,
    cache: DocumentationCache,
) -> ProjectDoc:
    """Generate and cache project-level documentation.

    Returns the cached ProjectDoc if one already exists, otherwise calls the LLM
    and stores the result before returning.
    """
    cached = cache.get_project_documentation(project_name)
    if cached is not None:
        logger.debug("Project %s found in cache", project_name)
        return cached

    # Build package context from already-cached PackageDoc entries
    package_contexts: list[str] = []
    for pkg in top_level_packages:
        pkg_doc = cache.get_package_documentation(pkg)
        if pkg_doc is not None:
            package_contexts.append(str(pkg_doc))

    packages_section = (
        "\n\n".join(package_contexts) if package_contexts else "No package documentation available."
    )

    prompt = f"""\
Describe the following software project.

<project>
Name: {project_name}
</project>

<packages>
{packages_section}
</packages>

Provide a concise high-level description of the project's purpose and main functionality. \
If you need additional context, use the available tools."""

    tool_registry = make_tool_registry(project_path, cache)

    result, _ = await llm.generate_agent(
        prompt=prompt,
        system_prompt=_SYS_PROJECT,
        allowed_tools=set(tool_registry.keys()),
        structured_output=_SCHEMA_PROJECT_DOC,
        response_validator=_validate_project_doc,
    )
    assert isinstance(result, dict)

    project_doc = ProjectDoc(
        name=project_name,
        description=result["description"],
        packages=top_level_packages,
    )
    cache.set_project_documentation(project_name, project_path, project_doc)
    logger.debug("Documented project %s", project_name)
    return project_doc
