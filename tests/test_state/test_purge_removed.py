from __future__ import annotations

import stat
from pathlib import Path

import pytest

from docai.state import initialize
from docai.state.artifact_status import get_status, purge_removed, set_status
from docai.state.datatypes import ArtifactStatus, GenerationStatus
from docai.state.errors import StateError


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    initialize()
    return tmp_path / ".docai"


def make_artifact_status(
    status: GenerationStatus,
    content_hash: str = "abc123",
    error: str | None = None,
) -> ArtifactStatus:
    return ArtifactStatus(status=status, content_hash=content_hash, error=error)


class TestHappyPath:
    @pytest.mark.integration
    def test_remove_entries_are_deleted_from_status(self, state_dir: Path) -> None:
        set_status({
            "src/gone.py": make_artifact_status(GenerationStatus.remove),
            "src/also_gone.py": make_artifact_status(GenerationStatus.remove, "def456"),
        })
        purge_removed()
        result = get_status()
        assert "src/gone.py" not in result
        assert "src/also_gone.py" not in result

    @pytest.mark.integration
    def test_non_remove_entries_are_preserved(self, state_dir: Path) -> None:
        set_status({
            "src/gone.py": make_artifact_status(GenerationStatus.remove),
            "src/main.py": make_artifact_status(GenerationStatus.complete),
            "src/draft.py": make_artifact_status(GenerationStatus.pending),
            "src/stale.py": make_artifact_status(GenerationStatus.deprecated),
            "src/broken.py": make_artifact_status(GenerationStatus.failed, error="timeout"),
        })
        purge_removed()
        result = get_status()
        assert "src/gone.py" not in result
        assert result["src/main.py"].status == GenerationStatus.complete
        assert result["src/draft.py"].status == GenerationStatus.pending
        assert result["src/stale.py"].status == GenerationStatus.deprecated
        assert result["src/broken.py"].status == GenerationStatus.failed


class TestEdgeCases:
    @pytest.mark.integration
    def test_no_op_when_no_remove_entries(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.complete)})
        purge_removed()
        result = get_status()
        assert result["src/main.py"].status == GenerationStatus.complete

    @pytest.mark.integration
    def test_no_op_on_empty_status(self, state_dir: Path) -> None:
        purge_removed()
        assert get_status() == {}


class TestErrorCases:
    @pytest.mark.integration
    def test_raises_when_status_json_not_readable(self, state_dir: Path) -> None:
        path = state_dir / "status.json"
        path.chmod(stat.S_IWUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                purge_removed()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    def test_raises_when_docai_dir_not_writable(self, state_dir: Path) -> None:
        state_dir.chmod(stat.S_IXUSR | stat.S_IRUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                purge_removed()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            state_dir.chmod(stat.S_IRWXU)
