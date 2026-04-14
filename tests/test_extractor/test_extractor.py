from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docai.discovery.datatypes import FileClassification, FileManifest, ManifestEntry
from docai.extractor.datatypes import FileAnalysis, FileType
from docai.extractor.errors import ExtractionError
from docai.extractor.extractor import extract
from docai.llm.errors import LLMError
from docai.llm.service import LLMService
from docai.state.errors import StateError


@pytest.fixture
def llm_service() -> MagicMock:
    service = MagicMock(spec=LLMService)
    service.generate = AsyncMock()
    return service


@pytest.fixture
def manifest_entry() -> ManifestEntry:
    return ManifestEntry(
        classification=FileClassification.processed,
        language="python",
        content_hash="abc123",
        override=None,
    )


@pytest.fixture
def file_manifest(manifest_entry: ManifestEntry) -> FileManifest:
    return {"src/foo.py": manifest_entry}


@pytest.fixture
def source_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    f = src / "foo.py"
    f.write_text("def run(): pass")
    return f


@pytest.fixture
def cached_analysis() -> FileAnalysis:
    return FileAnalysis(
        file_path="src/foo.py",
        file_type=FileType.source_file,
        entities=[],
        dependencies=[],
    )


@pytest.fixture
def extracted_analysis() -> FileAnalysis:
    return FileAnalysis(
        file_path="src/foo.py",
        file_type=FileType.source_file,
        entities=[],
        dependencies=["src/bar.py"],
    )


class TestExtractHappyPath:
    @pytest.mark.integration
    async def test_cache_hit_returns_cached_analysis(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
        cached_analysis: FileAnalysis,
    ) -> None:
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=cached_analysis),
            patch("docai.extractor.extractor.extract_with_llm") as mock_llm,
        ):
            result = await extract(
                file_path="src/foo.py",
                manifest_entry=manifest_entry,
                file_manifest=file_manifest,
                llm_service=llm_service,
            )

        assert result == cached_analysis
        mock_llm.assert_not_called()

    @pytest.mark.integration
    async def test_cache_miss_calls_extract_with_llm_and_returns_result(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
        extracted_analysis: FileAnalysis,
    ) -> None:
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=None),
            patch(
                "docai.extractor.extractor.extract_with_llm",
                new=AsyncMock(return_value=extracted_analysis),
            ),
            patch("docai.extractor.extractor.save_analysis"),
        ):
            result = await extract(
                file_path="src/foo.py",
                manifest_entry=manifest_entry,
                file_manifest=file_manifest,
                llm_service=llm_service,
            )

        assert result == extracted_analysis

    @pytest.mark.integration
    async def test_save_analysis_called_with_result(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
        extracted_analysis: FileAnalysis,
    ) -> None:
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=None),
            patch(
                "docai.extractor.extractor.extract_with_llm",
                new=AsyncMock(return_value=extracted_analysis),
            ),
            patch("docai.extractor.extractor.save_analysis") as mock_save,
        ):
            await extract(
                file_path="src/foo.py",
                manifest_entry=manifest_entry,
                file_manifest=file_manifest,
                llm_service=llm_service,
            )

        mock_save.assert_called_once_with(extracted_analysis)


class TestExtractReadErrors:
    @pytest.mark.integration
    async def test_unreadable_file_raises_extraction_read_failed(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        source_file.chmod(stat.S_IWUSR)
        try:
            with (
                patch("docai.extractor.extractor.get_analysis", return_value=None),
            ):
                with pytest.raises(ExtractionError) as exc_info:
                    await extract(
                        file_path="src/foo.py",
                        manifest_entry=manifest_entry,
                        file_manifest=file_manifest,
                        llm_service=llm_service,
                    )
            assert exc_info.value.code == "EXTRACTION_READ_FAILED"
        finally:
            source_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    async def test_read_error_message_contains_file_path(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        source_file.chmod(stat.S_IWUSR)
        try:
            with patch("docai.extractor.extractor.get_analysis", return_value=None):
                with pytest.raises(ExtractionError) as exc_info:
                    await extract(
                        file_path="src/foo.py",
                        manifest_entry=manifest_entry,
                        file_manifest=file_manifest,
                        llm_service=llm_service,
                    )
            assert exc_info.value.message == "Content not readable for file: src/foo.py"
        finally:
            source_file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    async def test_permission_error_preserved_as_cause_on_read_failure(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        source_file.chmod(stat.S_IWUSR)
        try:
            with patch("docai.extractor.extractor.get_analysis", return_value=None):
                with pytest.raises(ExtractionError) as exc_info:
                    await extract(
                        file_path="src/foo.py",
                        manifest_entry=manifest_entry,
                        file_manifest=file_manifest,
                        llm_service=llm_service,
                    )
            assert isinstance(exc_info.value.__cause__, PermissionError)
        finally:
            source_file.chmod(stat.S_IRUSR | stat.S_IWUSR)


class TestExtractErrorPropagation:
    @pytest.mark.integration
    async def test_docai_error_from_llm_propagates_unchanged(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        original = ExtractionError(
            message="File Analysis failed for src/foo.py",
            code="EXTRACTION_LLM_FAILED",
        )
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=None),
            patch(
                "docai.extractor.extractor.extract_with_llm",
                new=AsyncMock(side_effect=original),
            ),
        ):
            with pytest.raises(ExtractionError) as exc_info:
                await extract(
                    file_path="src/foo.py",
                    manifest_entry=manifest_entry,
                    file_manifest=file_manifest,
                    llm_service=llm_service,
                )

        assert exc_info.value is original

    @pytest.mark.integration
    async def test_unexpected_exception_raises_extraction_unexpected_error(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=None),
            patch(
                "docai.extractor.extractor.extract_with_llm",
                new=AsyncMock(side_effect=MemoryError("out of memory")),
            ),
        ):
            with pytest.raises(ExtractionError) as exc_info:
                await extract(
                    file_path="src/foo.py",
                    manifest_entry=manifest_entry,
                    file_manifest=file_manifest,
                    llm_service=llm_service,
                )

        assert exc_info.value.code == "EXTRACTION_UNEXPECTED_ERROR"

    @pytest.mark.integration
    async def test_unexpected_exception_message_contains_file_path_and_error(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        boom = MemoryError("out of memory")
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=None),
            patch(
                "docai.extractor.extractor.extract_with_llm",
                new=AsyncMock(side_effect=boom),
            ),
        ):
            with pytest.raises(ExtractionError) as exc_info:
                await extract(
                    file_path="src/foo.py",
                    manifest_entry=manifest_entry,
                    file_manifest=file_manifest,
                    llm_service=llm_service,
                )

        assert exc_info.value.message == f"File Analysis failed for src/foo.py: {boom}"

    @pytest.mark.integration
    async def test_unexpected_exception_preserved_as_cause(
        self,
        source_file: Path,
        manifest_entry: ManifestEntry,
        file_manifest: FileManifest,
        llm_service: MagicMock,
    ) -> None:
        original = MemoryError("out of memory")
        with (
            patch("docai.extractor.extractor.get_analysis", return_value=None),
            patch(
                "docai.extractor.extractor.extract_with_llm",
                new=AsyncMock(side_effect=original),
            ),
        ):
            with pytest.raises(ExtractionError) as exc_info:
                await extract(
                    file_path="src/foo.py",
                    manifest_entry=manifest_entry,
                    file_manifest=file_manifest,
                    llm_service=llm_service,
                )

        assert exc_info.value.__cause__ is original
