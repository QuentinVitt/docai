from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from unittest.mock import patch

from docai.extractor.datatypes import Entity, EntityCategory, FileAnalysis, FileType
from docai.state import initialize
from docai.state.analyses import get_analysis, purge_analyses, save_analysis
from docai.state.artifact_status import set_status
from docai.state.datatypes import ArtifactStatus, GenerationStatus
from docai.state.errors import StateError


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    initialize()
    return tmp_path / ".docai"


def _write_analysis(state_dir: Path, file_path: str, data: dict) -> Path:
    analysis_path = state_dir / "analyses" / (file_path + ".json")
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(json.dumps(data))
    return analysis_path


class TestGetAnalysisHappyPath:
    @pytest.mark.integration
    def test_returns_none_when_file_does_not_exist(self, state_dir: Path) -> None:
        result = get_analysis("src/docai/main.py")
        assert result is None

    @pytest.mark.integration
    def test_returns_correct_file_analysis(self, state_dir: Path) -> None:
        data = {
            "file_path": "src/docai/main.py",
            "file_type": "source_file",
            "entities": [],
            "dependencies": ["src/docai/utils.py"],
        }
        _write_analysis(state_dir, "src/docai/main.py", data)
        result = get_analysis("src/docai/main.py")
        assert result is not None
        assert result.file_path == "src/docai/main.py"
        assert result.file_type == FileType.source_file
        assert result.entities == []
        assert result.dependencies == ["src/docai/utils.py"]

    @pytest.mark.integration
    def test_deserializes_entities_correctly(self, state_dir: Path) -> None:
        data = {
            "file_path": "src/docai/parser.py",
            "file_type": "source_file",
            "entities": [
                {
                    "category": "callable",
                    "name": "parse",
                    "kind": "function",
                    "parent": None,
                    "signature": "def parse(content: str) -> AST:",
                }
            ],
            "dependencies": [],
        }
        _write_analysis(state_dir, "src/docai/parser.py", data)
        result = get_analysis("src/docai/parser.py")
        assert result is not None
        assert len(result.entities) == 1
        entity = result.entities[0]
        assert entity.category == EntityCategory.callable
        assert entity.name == "parse"
        assert entity.kind == "function"
        assert entity.parent is None
        assert entity.signature == "def parse(content: str) -> AST:"

    @pytest.mark.integration
    def test_reads_from_correct_subdirectory_for_nested_path(self, state_dir: Path) -> None:
        data = {
            "file_path": "src/docai/extractor/tier3.py",
            "file_type": "source_file",
            "entities": [],
            "dependencies": [],
        }
        _write_analysis(state_dir, "src/docai/extractor/tier3.py", data)
        result = get_analysis("src/docai/extractor/tier3.py")
        assert result is not None
        assert result.file_path == "src/docai/extractor/tier3.py"


class TestGetAnalysisErrors:
    @pytest.mark.integration
    def test_raises_permission_denied_when_file_unreadable(self, state_dir: Path) -> None:
        data = {
            "file_path": "src/docai/main.py",
            "file_type": "source_file",
            "entities": [],
            "dependencies": [],
        }
        analysis_path = _write_analysis(state_dir, "src/docai/main.py", data)
        analysis_path.chmod(stat.S_IWUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                get_analysis("src/docai/main.py")
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == f"No read permission on state artifact: {analysis_path}"
        finally:
            analysis_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    def test_raises_corrupt_on_invalid_json(self, state_dir: Path) -> None:
        analysis_path = state_dir / "analyses" / "src/docai/main.py.json"
        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        analysis_path.write_text("not valid json {{{")
        with pytest.raises(StateError) as exc_info:
            get_analysis("src/docai/main.py")
        assert exc_info.value.code == "STATE_CORRUPT"
        assert exc_info.value.message == f"State artifact corrupted: {analysis_path}"

    @pytest.mark.integration
    def test_raises_corrupt_on_wrong_json_structure(self, state_dir: Path) -> None:
        data = {"bad_field": "wrong"}
        analysis_path = _write_analysis(state_dir, "src/docai/main.py", data)
        with pytest.raises(StateError) as exc_info:
            get_analysis("src/docai/main.py")
        assert exc_info.value.code == "STATE_CORRUPT"
        assert exc_info.value.message == f"State artifact corrupted: {analysis_path}"


class TestSaveAnalysisHappyPath:
    @pytest.mark.integration
    def test_writes_to_correct_path(self, state_dir: Path) -> None:
        analysis = FileAnalysis(
            file_path="src/docai/main.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=[],
        )
        save_analysis(analysis)
        expected_path = state_dir / "analyses" / "src/docai/main.py.json"
        assert expected_path.exists()

    @pytest.mark.integration
    def test_written_content_round_trips_via_get_analysis(self, state_dir: Path) -> None:
        analysis = FileAnalysis(
            file_path="src/docai/main.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=["src/docai/utils.py"],
        )
        save_analysis(analysis)
        result = get_analysis("src/docai/main.py")
        assert result is not None
        assert result.file_path == analysis.file_path
        assert result.file_type == analysis.file_type
        assert result.dependencies == analysis.dependencies

    @pytest.mark.integration
    def test_creates_intermediate_directories_for_nested_path(self, state_dir: Path) -> None:
        analysis = FileAnalysis(
            file_path="src/docai/extractor/tier3.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=[],
        )
        save_analysis(analysis)
        expected_path = state_dir / "analyses" / "src/docai/extractor/tier3.py.json"
        assert expected_path.exists()

    @pytest.mark.integration
    def test_entities_serialized_and_readable_back(self, state_dir: Path) -> None:
        entity = Entity(
            category=EntityCategory.callable,
            name="run",
            kind="function",
            parent=None,
            signature="def run() -> None:",
        )
        analysis = FileAnalysis(
            file_path="src/docai/runner.py",
            file_type=FileType.source_file,
            entities=[entity],
            dependencies=[],
        )
        save_analysis(analysis)
        result = get_analysis("src/docai/runner.py")
        assert result is not None
        assert len(result.entities) == 1
        assert result.entities[0].name == "run"
        assert result.entities[0].category == EntityCategory.callable

    @pytest.mark.integration
    def test_overwrites_existing_file(self, state_dir: Path) -> None:
        original = FileAnalysis(
            file_path="src/docai/main.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=["src/docai/old.py"],
        )
        save_analysis(original)
        updated = FileAnalysis(
            file_path="src/docai/main.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=["src/docai/new.py"],
        )
        save_analysis(updated)
        result = get_analysis("src/docai/main.py")
        assert result is not None
        assert result.dependencies == ["src/docai/new.py"]

    @pytest.mark.integration
    def test_leaves_no_tmp_file_on_success(self, state_dir: Path) -> None:
        analysis = FileAnalysis(
            file_path="src/docai/main.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=[],
        )
        save_analysis(analysis)
        tmp_files = list((state_dir / "analyses").rglob("*.tmp"))
        assert tmp_files == []


class TestPurgeAnalysesHappyPath:
    @pytest.mark.integration
    def test_completes_without_error_when_analyses_dir_empty(self, state_dir: Path) -> None:
        purge_analyses()  # no files, no status entries — should not raise

    @pytest.mark.integration
    def test_deletes_file_with_deprecated_status(self, state_dir: Path) -> None:
        analysis = FileAnalysis(file_path="src/main.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(analysis)
        set_status({"src/main.py": ArtifactStatus(status=GenerationStatus.deprecated, content_hash="abc", error=None)})
        purge_analyses()
        assert not (state_dir / "analyses" / "src/main.py.json").exists()

    @pytest.mark.integration
    def test_deletes_file_with_remove_status(self, state_dir: Path) -> None:
        analysis = FileAnalysis(file_path="src/main.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(analysis)
        set_status({"src/main.py": ArtifactStatus(status=GenerationStatus.remove, content_hash="abc", error=None)})
        purge_analyses()
        assert not (state_dir / "analyses" / "src/main.py.json").exists()

    @pytest.mark.integration
    def test_deletes_orphaned_file_with_no_status_entry(self, state_dir: Path) -> None:
        analysis = FileAnalysis(file_path="src/main.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(analysis)
        set_status({})  # no entry for src/main.py
        purge_analyses()
        assert not (state_dir / "analyses" / "src/main.py.json").exists()

    @pytest.mark.integration
    @pytest.mark.parametrize("kept_status", [
        GenerationStatus.complete,
        GenerationStatus.pending,
        GenerationStatus.failed,
    ])
    def test_keeps_file_with_retained_status(self, state_dir: Path, kept_status: GenerationStatus) -> None:
        analysis = FileAnalysis(file_path="src/main.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(analysis)
        set_status({"src/main.py": ArtifactStatus(status=kept_status, content_hash="abc", error=None)})
        purge_analyses()
        assert (state_dir / "analyses" / "src/main.py.json").exists()

    @pytest.mark.integration
    def test_removes_empty_parent_directory_after_deletion(self, state_dir: Path) -> None:
        analysis = FileAnalysis(file_path="src/docai/main.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(analysis)
        set_status({"src/docai/main.py": ArtifactStatus(status=GenerationStatus.deprecated, content_hash="abc", error=None)})
        purge_analyses()
        assert not (state_dir / "analyses" / "src" / "docai").exists()
        assert not (state_dir / "analyses" / "src").exists()

    @pytest.mark.integration
    def test_does_not_remove_non_empty_parent_directory(self, state_dir: Path) -> None:
        kept = FileAnalysis(file_path="src/docai/keeper.py", file_type=FileType.source_file, entities=[], dependencies=[])
        gone = FileAnalysis(file_path="src/docai/gone.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(kept)
        save_analysis(gone)
        set_status({
            "src/docai/keeper.py": ArtifactStatus(status=GenerationStatus.complete, content_hash="abc", error=None),
            "src/docai/gone.py": ArtifactStatus(status=GenerationStatus.deprecated, content_hash="def", error=None),
        })
        purge_analyses()
        assert not (state_dir / "analyses" / "src" / "docai" / "gone.py.json").exists()
        assert (state_dir / "analyses" / "src" / "docai" / "keeper.py.json").exists()
        assert (state_dir / "analyses" / "src" / "docai").exists()

    @pytest.mark.integration
    def test_mixed_statuses_only_deletes_purgeable_files(self, state_dir: Path) -> None:
        for file_path in ["src/a.py", "src/b.py", "src/c.py", "src/d.py"]:
            save_analysis(FileAnalysis(file_path=file_path, file_type=FileType.source_file, entities=[], dependencies=[]))
        set_status({
            "src/a.py": ArtifactStatus(status=GenerationStatus.complete, content_hash="a", error=None),
            "src/b.py": ArtifactStatus(status=GenerationStatus.deprecated, content_hash="b", error=None),
            "src/c.py": ArtifactStatus(status=GenerationStatus.remove, content_hash="c", error=None),
            # src/d.py — orphaned, no entry
        })
        purge_analyses()
        assert (state_dir / "analyses" / "src" / "a.py.json").exists()
        assert not (state_dir / "analyses" / "src" / "b.py.json").exists()
        assert not (state_dir / "analyses" / "src" / "c.py.json").exists()
        assert not (state_dir / "analyses" / "src" / "d.py.json").exists()


class TestPurgeAnalysesErrors:
    @pytest.mark.integration
    def test_wraps_state_error_from_get_status(self, state_dir: Path) -> None:
        original = StateError(message="State artifact corrupted: status.json", code="STATE_CORRUPT")
        with patch("docai.state.analyses.get_status", side_effect=original):
            with pytest.raises(StateError) as exc_info:
                purge_analyses()
        assert exc_info.value.code == "STATE_PURGE_FAILED"
        assert exc_info.value.message == "Analysis purge failed"
        assert exc_info.value.__cause__ is original

    @pytest.mark.integration
    def test_wraps_permission_error_during_file_deletion(self, state_dir: Path) -> None:
        analysis = FileAnalysis(file_path="src/main.py", file_type=FileType.source_file, entities=[], dependencies=[])
        save_analysis(analysis)
        set_status({"src/main.py": ArtifactStatus(status=GenerationStatus.deprecated, content_hash="abc", error=None)})
        analysis_path = state_dir / "analyses" / "src" / "main.py.json"
        analysis_path.chmod(stat.S_IRUSR)
        (state_dir / "analyses" / "src").chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                purge_analyses()
            assert exc_info.value.code == "STATE_PURGE_FAILED"
            assert exc_info.value.message == f"Analysis purge failed: permission denied on {analysis_path}"
            assert isinstance(exc_info.value.__cause__, PermissionError)
        finally:
            (state_dir / "analyses" / "src").chmod(stat.S_IRWXU)
            analysis_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


class TestSaveAnalysisErrors:
    @pytest.mark.integration
    def test_raises_permission_denied_on_unwritable_directory(self, state_dir: Path) -> None:
        analyses_dir = state_dir / "analyses"
        analyses_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            analysis = FileAnalysis(
                file_path="src/docai/main.py",
                file_type=FileType.source_file,
                entities=[],
                dependencies=[],
            )
            with pytest.raises(StateError) as exc_info:
                save_analysis(analysis)
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            analyses_dir.chmod(stat.S_IRWXU)
