from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from docai.discovery.datatypes import FileClassification, FileManifest, FileOverride, ManifestEntry
from docai.extractor.datatypes import Entity, EntityCategory, FileAnalysis, FileType
from docai.extractor.errors import ExtractionError
from docai.extractor.llm_fallback import EntityList, FileTypeAndDeps, extract_with_llm
from docai.llm.errors import LLMError
from docai.llm.service import LLMService


@pytest.fixture
def llm_service() -> MagicMock:
    service = MagicMock(spec=LLMService)
    service.generate = AsyncMock()
    return service


@pytest.fixture
def processed_entry() -> ManifestEntry:
    return ManifestEntry(
        classification=FileClassification.processed,
        language="python",
        content_hash="abc123",
        override=None,
    )


@pytest.fixture
def config_entry() -> ManifestEntry:
    return ManifestEntry(
        classification=FileClassification.processed,
        language="yaml",
        content_hash="def456",
        override=None,
    )


@pytest.fixture
def file_manifest(processed_entry: ManifestEntry) -> FileManifest:
    return {"src/foo.py": processed_entry}


def _make_generate_side_effect(
    type_and_deps: FileTypeAndDeps,
    entity_list: EntityList | None = None,
) -> list:
    """Returns side_effect list: first call returns type_and_deps, second returns entity_list."""
    if entity_list is not None:
        return [type_and_deps, entity_list]
    return [type_and_deps]


class TestLLMFallbackHappyPath:
    @pytest.mark.llm
    async def test_returns_file_analysis_from_llm_for_source_file(
        self,
        llm_service: MagicMock,
        processed_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        entity = Entity(
            category=EntityCategory.callable,
            name="run",
            kind="function",
            parent=None,
            signature="def run() -> None:",
        )
        llm_service.generate.side_effect = _make_generate_side_effect(
            FileTypeAndDeps(file_type=FileType.source_file, dependencies=["src/bar.py"]),
            EntityList(entities=[entity]),
        )

        result = await extract_with_llm(
            file_path="src/foo.py",
            content="def run() -> None: ...",
            manifest_entry=processed_entry,
            file_manifest=file_manifest,
            llm_service=llm_service,
        )

        assert result.file_path == "src/foo.py"
        assert result.file_type == FileType.source_file
        assert result.dependencies == ["src/bar.py"]
        assert len(result.entities) == 1
        assert result.entities[0].name == "run"

    @pytest.mark.llm
    async def test_returns_file_analysis_with_empty_entities_for_config_file(
        self,
        llm_service: MagicMock,
        config_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        llm_service.generate.side_effect = _make_generate_side_effect(
            FileTypeAndDeps(file_type=FileType.config_file, dependencies=[]),
        )

        result = await extract_with_llm(
            file_path="src/config.yaml",
            content="key: value",
            manifest_entry=config_entry,
            file_manifest=file_manifest,
            llm_service=llm_service,
        )

        assert result.entities == []
        assert result.file_type == FileType.config_file

    @pytest.mark.llm
    async def test_first_generate_call_uses_file_type_and_deps_structured_output(
        self,
        llm_service: MagicMock,
        processed_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        llm_service.generate.side_effect = _make_generate_side_effect(
            FileTypeAndDeps(file_type=FileType.source_file, dependencies=[]),
            EntityList(entities=[]),
        )

        await extract_with_llm(
            file_path="src/foo.py",
            content="x = 1",
            manifest_entry=processed_entry,
            file_manifest=file_manifest,
            llm_service=llm_service,
        )

        first_call_kwargs = llm_service.generate.call_args_list[0][1]
        assert first_call_kwargs.get("structured_output") is FileTypeAndDeps

    @pytest.mark.llm
    async def test_entity_extraction_skipped_for_non_source_file(
        self,
        llm_service: MagicMock,
        config_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        llm_service.generate.side_effect = _make_generate_side_effect(
            FileTypeAndDeps(file_type=FileType.config_file, dependencies=[]),
        )

        await extract_with_llm(
            file_path="src/config.yaml",
            content="key: value",
            manifest_entry=config_entry,
            file_manifest=file_manifest,
            llm_service=llm_service,
        )

        assert llm_service.generate.call_count == 1

    @pytest.mark.llm
    async def test_empty_file_manifest_still_calls_llm(
        self,
        llm_service: MagicMock,
        processed_entry: ManifestEntry,
    ) -> None:
        llm_service.generate.side_effect = _make_generate_side_effect(
            FileTypeAndDeps(file_type=FileType.source_file, dependencies=[]),
            EntityList(entities=[]),
        )

        result = await extract_with_llm(
            file_path="src/foo.py",
            content="x = 1",
            manifest_entry=processed_entry,
            file_manifest={},
            llm_service=llm_service,
        )

        assert llm_service.generate.call_count == 2
        assert result.file_path == "src/foo.py"


class TestLLMFallbackErrors:
    @pytest.mark.llm
    async def test_llm_error_raises_extraction_llm_failed(
        self,
        llm_service: MagicMock,
        processed_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        llm_service.generate.side_effect = LLMError(
            message="All models failed to produce a valid response",
            code="LLM_ALL_MODELS_FAILED",
        )

        with pytest.raises(ExtractionError) as exc_info:
            await extract_with_llm(
                file_path="src/foo.py",
                content="x = 1",
                manifest_entry=processed_entry,
                file_manifest=file_manifest,
                llm_service=llm_service,
            )

        assert exc_info.value.code == "EXTRACTION_LLM_FAILED"

    @pytest.mark.llm
    async def test_extraction_error_message_contains_file_path(
        self,
        llm_service: MagicMock,
        processed_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        llm_service.generate.side_effect = LLMError(
            message="rate limit",
            code="LLM_ALL_MODELS_FAILED",
        )

        with pytest.raises(ExtractionError) as exc_info:
            await extract_with_llm(
                file_path="src/foo.py",
                content="x = 1",
                manifest_entry=processed_entry,
                file_manifest=file_manifest,
                llm_service=llm_service,
            )

        assert exc_info.value.message == "File Analysis failed for src/foo.py"

    @pytest.mark.llm
    async def test_llm_error_preserved_as_cause(
        self,
        llm_service: MagicMock,
        processed_entry: ManifestEntry,
        file_manifest: FileManifest,
    ) -> None:
        original = LLMError(
            message="All models failed to produce a valid response",
            code="LLM_ALL_MODELS_FAILED",
        )
        llm_service.generate.side_effect = original

        with pytest.raises(ExtractionError) as exc_info:
            await extract_with_llm(
                file_path="src/foo.py",
                content="x = 1",
                manifest_entry=processed_entry,
                file_manifest=file_manifest,
                llm_service=llm_service,
            )

        assert exc_info.value.__cause__ is original
