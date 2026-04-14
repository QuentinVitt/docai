from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from docai.discovery.datatypes import FileManifest, ManifestEntry
from docai.extractor.datatypes import Entity, FileAnalysis, FileType
from docai.extractor.errors import ExtractionError
from docai.llm.errors import LLMError
from docai.llm.service import LLMService


# --- Structured output models ---

class FileTypeAndDeps(BaseModel):
    file_type: FileType
    dependencies: list[str]


class EntityList(BaseModel):
    entities: list[Entity]


# --- System prompts ---

_SYSTEM_PROMPT_TYPE_AND_DEPS = """\
You are an expert code analyst. Your task is to classify a file and identify \
which other project files it directly depends on — meaning files it imports, \
includes, or otherwise references at the source level.

File type rules:
- source_file: a programming language file with functions, classes, or other \
  named entities (e.g. .py, .rs, .js, .go)
- source_like_config: not a programming language, but contains import-like \
  constructs that reference other project files (e.g. .scss with @use, \
  Makefile with include, HTML template with {% import %})
- config_file: a configuration file with no imports to other project files \
  (e.g. .yaml, .toml, .json config, .env)
- other: cannot be classified into any of the above categories

Dependency rules:
- Only return files that appear in the provided project file list.
- Do not include standard library modules or third-party packages.
- Only include direct dependencies (files this file itself references).
- If file_type is source_like_config, dependencies must not be empty — \
  source_like_config means the file imports other project files.
- If there are no project-internal dependencies, return an empty list.\
"""

_SYSTEM_PROMPT_ENTITIES = """\
You are an expert code analyst. Your task is to extract the named entities \
from a source file.

Entity categories:
- callable: functions, methods, constructors, lambdas, closures
- macro: preprocessor macros, compile-time code generators, decorators \
  that transform structure
- type: classes, interfaces, structs, enums, type aliases, protocols, traits
- value: module-level constants, global variables, exported values
- implementation: impl blocks, trait implementations, mixin applications \
  (language constructs that attach behaviour to a type without being the type)

Rules:
- name: the entity's own name only (not qualified)
- kind: the specific language construct (e.g. "function", "class", "method", \
  "constant", "enum")
- parent: dotted scope path from module root for nested entities \
  (e.g. "OuterClass.InnerClass"), or null if top-level
- signature: the declaration line or signature, or null if not applicable
- Extract all named entities visible at the module level and nested within \
  types. Do not extract anonymous or local-scope-only constructs.\
"""


# --- Validators ---

def _make_type_and_deps_validator(
    file_manifest: FileManifest,
) -> Callable[[str | BaseModel], str | None]:
    all_files = set(file_manifest)

    def validate(result: str | BaseModel) -> str | None:
        if not isinstance(result, FileTypeAndDeps):
            return "Expected a FileTypeAndDeps object"
        invalid = [d for d in result.dependencies if d not in all_files]
        if invalid:
            return (
                f"The following paths are not in the project file list: "
                f"{', '.join(invalid)}. Only return paths that appear exactly "
                f"in the provided project_files list."
            )
        if result.file_type == FileType.source_like_config and not result.dependencies:
            return (
                "file_type is source_like_config but dependencies is empty. "
                "source_like_config means the file imports other project files. "
                "Either provide a non-empty dependencies list or correct the file_type."
            )
        return None

    return validate


# --- Internal extraction calls ---

async def _extract_type_and_deps(
    file_path: str,
    content: str,
    manifest_entry: ManifestEntry,
    file_manifest: FileManifest,
    llm_service: LLMService,
) -> FileTypeAndDeps:
    file_list = "\n".join(f"- {p}" for p in sorted(file_manifest))
    lang = manifest_entry.language or "unknown"
    prompt = (
        f"Classify the following file and identify its project-internal dependencies.\n\n"
        f"<file>\n"
        f"Path: {file_path}\n"
        f"Language: {lang}\n"
        f"Classification: {manifest_entry.classification.value}\n"
        f"</file>\n\n"
        f"<project_files>\n"
        f"Only return dependencies whose paths appear in this list:\n"
        f"{file_list}\n"
        f"</project_files>\n\n"
        f"<file_content>\n"
        f"```{lang}\n{content}\n```\n"
        f"</file_content>"
    )
    result = await llm_service.generate(
        prompt,
        system_prompt=_SYSTEM_PROMPT_TYPE_AND_DEPS,
        structured_output=FileTypeAndDeps,
        validator=_make_type_and_deps_validator(file_manifest),
    )
    return result  # type: ignore[return-value]


async def _extract_entities(
    file_path: str,
    content: str,
    manifest_entry: ManifestEntry,
    llm_service: LLMService,
) -> EntityList:
    lang = manifest_entry.language or "unknown"
    prompt = (
        f"Extract all named entities from the following source file.\n\n"
        f"<file>\n"
        f"Path: {file_path}\n"
        f"Language: {lang}\n"
        f"</file>\n\n"
        f"<file_content>\n"
        f"```{lang}\n{content}\n```\n"
        f"</file_content>"
    )
    result = await llm_service.generate(
        prompt,
        system_prompt=_SYSTEM_PROMPT_ENTITIES,
        structured_output=EntityList,
    )
    return result  # type: ignore[return-value]


# --- Public entry point ---

async def extract_with_llm(
    file_path: str,
    content: str,
    manifest_entry: ManifestEntry,
    file_manifest: FileManifest,
    llm_service: LLMService,
) -> FileAnalysis:
    try:
        type_and_deps = await _extract_type_and_deps(
            file_path, content, manifest_entry, file_manifest, llm_service
        )
        if type_and_deps.file_type == FileType.source_file:
            entity_list = await _extract_entities(
                file_path, content, manifest_entry, llm_service
            )
            entities = entity_list.entities
        else:
            entities = []
    except LLMError as exc:
        raise ExtractionError(
            code="EXTRACTION_LLM_FAILED",
            message=f"File Analysis failed for {file_path}",
        ) from exc

    return FileAnalysis(
        file_path=file_path,
        file_type=type_and_deps.file_type,
        entities=entities,
        dependencies=type_and_deps.dependencies,
    )
