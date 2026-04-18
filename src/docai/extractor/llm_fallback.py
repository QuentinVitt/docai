from __future__ import annotations

import logging
from typing import Callable

from pydantic import BaseModel

from docai.discovery.datatypes import FileManifest, ManifestEntry
from docai.extractor.datatypes import Entity, EntityCategory, FileAnalysis, FileType
from docai.extractor.errors import ExtractionError
from docai.llm.errors import LLMError
from docai.llm.service import LLMService
from docai.prompts.loader import load_prompt

# --- Structured output models ---


class FileTypeAndDeps(BaseModel):
    file_type: FileType
    dependencies: list[str]


class EntityList(BaseModel):
    entities: list[Entity]


logger = logging.getLogger(__name__)


# --- Chunking helpers ---


def _build_chunks(
    lines: list[str],
    chunk_size: int,
    header_size: int,
    overlap: int,
) -> list[str]:
    if len(lines) <= chunk_size:
        return ["\n".join(lines)]
    header = lines[:header_size]
    remaining = lines[header_size:]
    step = chunk_size - overlap
    header_str = "\n".join(header)
    chunks = []
    for i in range(0, len(remaining), step):
        body = "\n".join(remaining[i : i + chunk_size])
        chunks.append(f"{header_str}\n# ...\n{body}")
    return chunks


def _merge_entities(*entity_lists: EntityList) -> EntityList:
    seen: set[tuple[str, EntityCategory]] = set()
    merged: list[Entity] = []
    for entity_list in entity_lists:
        for entity in entity_list.entities:
            key = (entity.name, entity.category)
            if key not in seen:
                seen.add(key)
                merged.append(entity)
    return EntityList(entities=merged)




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
    lang = manifest_entry.language or "unknown"
    file_list = "\n".join(f"- {p}" for p in sorted(file_manifest))
    template = load_prompt("extractor/type_and_deps", language=lang)
    prompt = template.user_prompt_template.format_map({
        "file_path": file_path,
        "language": lang,
        "classification": manifest_entry.classification.value,
        "file_list": file_list,
        "content": content,
    })
    result = await llm_service.generate(
        prompt,
        system_prompt=template.system_prompt_template,
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
    template = load_prompt("extractor/entities", language=lang)
    prompt = template.user_prompt_template.format_map({
        "file_path": file_path,
        "language": lang,
        "content": content,
    })
    result = await llm_service.generate(
        prompt,
        system_prompt=template.system_prompt_template,
        structured_output=EntityList,
    )
    return _merge_entities(result)  # type: ignore[arg-type]


async def _extract_entities_chunked(
    file_path: str,
    content: str,
    manifest_entry: ManifestEntry,
    llm_service: LLMService,
    *,
    chunk_size: int = 750,
    header_size: int = 100,
    overlap: int = 200,
) -> EntityList:
    lines = content.splitlines()
    chunks = _build_chunks(
        lines, chunk_size=chunk_size, header_size=header_size, overlap=overlap
    )

    if len(chunks) > 1:
        logger.warning(
            "Large file '%s' (%d lines) split into %d chunks — "
            "entity parent attribution may be imperfect",
            file_path,
            len(lines),
            len(chunks),
        )

    results: list[EntityList] = []
    for i, chunk_content in enumerate(chunks):
        try:
            entity_list = await _extract_entities(
                file_path, chunk_content, manifest_entry, llm_service
            )
            results.append(entity_list)
        except LLMError:
            logger.warning(
                "Entity extraction failed for chunk %d/%d of '%s' — skipping",
                i + 1,
                len(chunks),
                file_path,
            )

    return _merge_entities(*results) if results else EntityList(entities=[])


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
            entity_list = await _extract_entities_chunked(
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
