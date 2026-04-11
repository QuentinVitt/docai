from __future__ import annotations

import stat
from pathlib import Path

import pytest

from docai.state import initialize
from docai.state.artifact_status import change_status, get_status, set_status
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
    def test_status_field_is_updated_and_persisted(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending)})
        change_status("src/main.py", GenerationStatus.complete)
        assert get_status()["src/main.py"].status == GenerationStatus.complete

    @pytest.mark.integration
    def test_error_message_is_persisted_when_provided(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending)})
        change_status("src/main.py", GenerationStatus.failed, error="LLM timeout")
        assert get_status()["src/main.py"].error == "LLM timeout"

    @pytest.mark.integration
    def test_error_field_is_none_when_not_provided(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending)})
        change_status("src/main.py", GenerationStatus.complete)
        assert get_status()["src/main.py"].error is None

    @pytest.mark.integration
    def test_existing_error_is_cleared_when_not_provided(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.failed, error="old error")})
        change_status("src/main.py", GenerationStatus.pending)
        assert get_status()["src/main.py"].error is None

    @pytest.mark.integration
    def test_content_hash_is_preserved(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending, content_hash="deadbeef")})
        change_status("src/main.py", GenerationStatus.complete)
        assert get_status()["src/main.py"].content_hash == "deadbeef"

    @pytest.mark.integration
    def test_other_entries_are_not_affected(self, state_dir: Path) -> None:
        set_status({
            "src/main.py": make_artifact_status(GenerationStatus.pending),
            "src/utils.py": make_artifact_status(GenerationStatus.complete, content_hash="def456"),
        })
        change_status("src/main.py", GenerationStatus.complete)
        utils = get_status()["src/utils.py"]
        assert utils.status == GenerationStatus.complete
        assert utils.content_hash == "def456"

    @pytest.mark.integration
    @pytest.mark.parametrize("new_status", [
        GenerationStatus.pending,
        GenerationStatus.complete,
        GenerationStatus.deprecated,
        GenerationStatus.failed,
        GenerationStatus.remove,
    ])
    def test_all_generation_status_values_accepted(
        self, state_dir: Path, new_status: GenerationStatus
    ) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending)})
        change_status("src/main.py", new_status)
        assert get_status()["src/main.py"].status == new_status


class TestErrorCases:
    @pytest.mark.integration
    def test_raises_when_path_not_in_status(self, state_dir: Path) -> None:
        with pytest.raises(StateError) as exc_info:
            change_status("src/missing.py", GenerationStatus.complete)
        assert exc_info.value.code == "STATE_ENTRY_NOT_FOUND"

    @pytest.mark.integration
    def test_raises_exact_message_when_path_not_found(self, state_dir: Path) -> None:
        with pytest.raises(StateError) as exc_info:
            change_status("src/missing.py", GenerationStatus.complete)
        assert exc_info.value.message == "Status entry not found: src/missing.py"

    @pytest.mark.integration
    def test_raises_when_status_json_not_readable(self, state_dir: Path) -> None:
        path = state_dir / "status.json"
        path.chmod(stat.S_IWUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                change_status("src/main.py", GenerationStatus.complete)
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    def test_raises_when_docai_dir_not_writable(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending)})
        state_dir.chmod(stat.S_IXUSR | stat.S_IRUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                change_status("src/main.py", GenerationStatus.complete)
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            state_dir.chmod(stat.S_IRWXU)
