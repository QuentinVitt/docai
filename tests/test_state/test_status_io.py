from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from docai.state import initialize
from docai.state.artifact_status import get_status, set_status
from docai.state.datatypes import ArtifactStatus, GenerationStatus
from docai.state.errors import StateError


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    initialize()
    return tmp_path / ".docai"


class TestGetStatusHappyPath:
    @pytest.mark.integration
    def test_returns_empty_dict_when_status_json_is_empty(self, state_dir: Path) -> None:
        result = get_status()
        assert result == {}

    @pytest.mark.integration
    def test_returns_correct_artifact_status_fields(self, state_dir: Path) -> None:
        data = {
            "src/main.py": {
                "status": "complete",
                "content_hash": "abc123",
                "error": None,
            }
        }
        (state_dir / "status.json").write_text(json.dumps(data))
        result = get_status()
        assert result == {
            "src/main.py": ArtifactStatus(
                status=GenerationStatus.complete,
                content_hash="abc123",
                error=None,
            )
        }

    @pytest.mark.integration
    @pytest.mark.parametrize("status_value", [
        GenerationStatus.pending,
        GenerationStatus.complete,
        GenerationStatus.deprecated,
        GenerationStatus.failed,
        GenerationStatus.remove,
    ])
    def test_deserializes_all_generation_status_values(
        self, state_dir: Path, status_value: GenerationStatus
    ) -> None:
        data = {
            "src/main.py": {
                "status": status_value.value,
                "content_hash": "abc123",
                "error": None,
            }
        }
        (state_dir / "status.json").write_text(json.dumps(data))
        result = get_status()
        assert result["src/main.py"].status == status_value


class TestSetStatusHappyPath:
    @pytest.mark.integration
    def test_round_trips_populated_dict(self, state_dir: Path) -> None:
        statuses = {
            "src/main.py": ArtifactStatus(
                status=GenerationStatus.complete,
                content_hash="abc123",
                error=None,
            ),
            "src/utils.py": ArtifactStatus(
                status=GenerationStatus.failed,
                content_hash="def456",
                error="LLM timeout",
            ),
        }
        set_status(statuses)
        assert get_status() == statuses

    @pytest.mark.integration
    def test_empty_dict_round_trips_to_empty_dict(self, state_dir: Path) -> None:
        set_status({})
        assert get_status() == {}

    @pytest.mark.integration
    def test_error_none_round_trips_correctly(self, state_dir: Path) -> None:
        statuses = {
            "src/main.py": ArtifactStatus(
                status=GenerationStatus.pending,
                content_hash="abc123",
                error=None,
            )
        }
        set_status(statuses)
        result = get_status()
        assert result["src/main.py"].error is None


class TestGetStatusErrors:
    @pytest.mark.integration
    def test_raises_when_status_json_not_readable(self, state_dir: Path) -> None:
        path = state_dir / "status.json"
        path.chmod(stat.S_IWUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                get_status()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == f"No read permission on state artifact: {path}"
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    def test_raises_on_invalid_json(self, state_dir: Path) -> None:
        path = state_dir / "status.json"
        path.write_text("not valid json {{{")
        with pytest.raises(StateError) as exc_info:
            get_status()
        assert exc_info.value.code == "STATE_CORRUPT"
        assert exc_info.value.message == f"State artifact corrupted: {path}"

    @pytest.mark.integration
    def test_raises_on_invalid_artifact_status_structure(self, state_dir: Path) -> None:
        path = state_dir / "status.json"
        path.write_text(json.dumps({"src/main.py": {"bad_field": "wrong"}}))
        with pytest.raises(StateError) as exc_info:
            get_status()
        assert exc_info.value.code == "STATE_CORRUPT"
        assert exc_info.value.message == f"State artifact corrupted: {path}"


class TestSetStatusErrors:
    @pytest.mark.integration
    def test_raises_when_docai_dir_not_writable(self, state_dir: Path) -> None:
        path = state_dir / "status.json"
        state_dir.chmod(stat.S_IXUSR | stat.S_IRUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                set_status({})
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == f"No write permission on state artifact: {path}"
        finally:
            state_dir.chmod(stat.S_IRWXU)
