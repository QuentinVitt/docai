from __future__ import annotations

from pathlib import Path

from docai.discovery.datatypes import FileManifest, ManifestEntry
from docai.errors import DocaiError
from docai.extractor.datatypes import FileAnalysis
from docai.extractor.errors import ExtractionError
from docai.extractor.llm_fallback import extract_with_llm
from docai.llm.service import LLMService
from docai.state.analyses import get_analysis, save_analysis


async def extract(
    file_path: str,
    manifest_entry: ManifestEntry,
    file_manifest: FileManifest,
    llm_service: LLMService | None = None,
) -> FileAnalysis:
    cached = get_analysis(file_path)
    if cached is not None:
        return cached

    try:
        try:
            content = Path(file_path).read_text()
        except PermissionError as exc:
            raise ExtractionError(
                code="EXTRACTION_READ_FAILED",
                message=f"Content not readable for file: {file_path}",
            ) from exc

        result = await extract_with_llm(
            file_path=file_path,
            content=content,
            manifest_entry=manifest_entry,
            file_manifest=file_manifest,
            llm_service=llm_service,  # type: ignore[arg-type]
        )
        save_analysis(result)
        return result

    except DocaiError:
        raise
    except Exception as exc:
        raise ExtractionError(
            code="EXTRACTION_UNEXPECTED_ERROR",
            message=f"File Analysis failed for {file_path}: {exc}",
        ) from exc
