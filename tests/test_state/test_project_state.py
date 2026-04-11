from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from docai.state import STATE_VERSION, initialize, reinitialize, startup
from docai.state.errors import StateError


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def initialized_dir(project_dir: Path) -> Path:
    initialize()
    return project_dir


class TestInitializeCreatesStructure:
    @pytest.mark.integration
    def test_creates_docai_directory(self, project_dir: Path) -> None:
        initialize()
        assert (project_dir / ".docai").is_dir()

    @pytest.mark.integration
    def test_creates_required_files(self, project_dir: Path) -> None:
        initialize()
        docai = project_dir / ".docai"
        assert (docai / "version").is_file()
        assert (docai / "purposes.json").is_file()
        assert (docai / "graph.json").is_file()
        assert (docai / "status.json").is_file()

    @pytest.mark.integration
    def test_creates_required_subdirectories(self, project_dir: Path) -> None:
        initialize()
        docai = project_dir / ".docai"
        assert (docai / "analyses").is_dir()
        assert (docai / "docs").is_dir()


class TestInitializeContents:
    @pytest.mark.integration
    def test_version_file_contains_state_version(self, project_dir: Path) -> None:
        initialize()
        content = (project_dir / ".docai" / "version").read_text().strip()
        assert content == STATE_VERSION

    @pytest.mark.integration
    def test_json_files_contain_empty_object(self, project_dir: Path) -> None:
        initialize()
        docai = project_dir / ".docai"
        for filename in ("purposes.json", "graph.json", "status.json"):
            content = json.loads((docai / filename).read_text())
            assert content == {}


class TestInitializeIdempotent:
    @pytest.mark.integration
    def test_does_not_raise_when_fully_initialized(self, project_dir: Path) -> None:
        initialize()
        initialize()

    @pytest.mark.integration
    def test_does_not_overwrite_existing_files(self, project_dir: Path) -> None:
        initialize()
        sentinel = "existing content"
        (project_dir / ".docai" / "purposes.json").write_text(sentinel)
        initialize()
        content = (project_dir / ".docai" / "purposes.json").read_text()
        assert content == sentinel

    @pytest.mark.integration
    def test_creates_missing_artifacts_when_partially_initialized(
        self, project_dir: Path
    ) -> None:
        (project_dir / ".docai").mkdir()
        (project_dir / ".docai" / "version").write_text("1")
        initialize()
        assert (project_dir / ".docai" / "purposes.json").is_file()
        assert (project_dir / ".docai" / "graph.json").is_file()
        assert (project_dir / ".docai" / "status.json").is_file()
        assert (project_dir / ".docai" / "analyses").is_dir()
        assert (project_dir / ".docai" / "docs").is_dir()


class TestInitializeErrors:
    @pytest.mark.integration
    def test_raises_when_project_root_not_readable_or_writable(
        self, project_dir: Path
    ) -> None:
        project_dir.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                initialize()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on project root: {project_dir}"
            )
        finally:
            project_dir.chmod(stat.S_IRWXU)

    @pytest.mark.integration
    def test_raises_when_docai_dir_not_readable_or_writable(
        self, project_dir: Path
    ) -> None:
        docai = project_dir / ".docai"
        docai.mkdir()
        docai.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                initialize()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on state directory: {docai}"
            )
        finally:
            docai.chmod(stat.S_IRWXU)


class TestReinitializeCreatesStructure:
    @pytest.mark.integration
    def test_creates_all_artifacts_when_docai_does_not_exist(
        self, project_dir: Path
    ) -> None:
        reinitialize()
        docai = project_dir / ".docai"
        assert docai.is_dir()
        assert (docai / "version").is_file()
        assert (docai / "purposes.json").is_file()
        assert (docai / "graph.json").is_file()
        assert (docai / "status.json").is_file()
        assert (docai / "analyses").is_dir()
        assert (docai / "docs").is_dir()

    @pytest.mark.integration
    def test_recreates_all_artifacts_when_docai_exists(
        self, project_dir: Path
    ) -> None:
        initialize()
        reinitialize()
        docai = project_dir / ".docai"
        assert docai.is_dir()
        assert (docai / "version").is_file()
        assert (docai / "purposes.json").is_file()
        assert (docai / "graph.json").is_file()
        assert (docai / "status.json").is_file()
        assert (docai / "analyses").is_dir()
        assert (docai / "docs").is_dir()


class TestReinitializeOverwrites:
    @pytest.mark.integration
    def test_overwrites_existing_file_content(self, project_dir: Path) -> None:
        initialize()
        (project_dir / ".docai" / "purposes.json").write_text("custom content")
        reinitialize()
        content = json.loads((project_dir / ".docai" / "purposes.json").read_text())
        assert content == {}


class TestReinitializeErrors:
    @pytest.mark.integration
    def test_raises_when_project_root_not_readable_or_writable(
        self, project_dir: Path
    ) -> None:
        project_dir.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                reinitialize()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on project root: {project_dir}"
            )
        finally:
            project_dir.chmod(stat.S_IRWXU)


class TestStartupHappyPath:
    @pytest.mark.integration
    def test_returns_none_on_healthy_state(self, initialized_dir: Path) -> None:
        result = startup()
        assert result is None

    @pytest.mark.integration
    def test_writes_current_pid_to_lock_file(self, initialized_dir: Path) -> None:
        startup()
        lock = initialized_dir / ".docai" / "lock"
        assert lock.read_text().strip() == str(os.getpid())


class TestStartupPermissions:
    @pytest.mark.integration
    def test_raises_when_project_root_not_readable_or_writable(
        self, initialized_dir: Path
    ) -> None:
        initialized_dir.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                startup()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on project root: {initialized_dir}"
            )
        finally:
            initialized_dir.chmod(stat.S_IRWXU)

    @pytest.mark.integration
    def test_raises_when_docai_dir_not_readable_or_writable(
        self, initialized_dir: Path
    ) -> None:
        docai = initialized_dir / ".docai"
        docai.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                startup()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on state directory: {docai}"
            )
        finally:
            docai.chmod(stat.S_IRWXU)

    @pytest.mark.integration
    @pytest.mark.parametrize("name", ["version", "purposes.json", "graph.json", "status.json"])
    def test_raises_when_file_artifact_not_readable_or_writable(
        self, initialized_dir: Path, name: str
    ) -> None:
        path = initialized_dir / ".docai" / name
        path.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                startup()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on state artifact: {path}"
            )
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    @pytest.mark.parametrize("name", ["analyses", "docs"])
    def test_raises_when_dir_artifact_not_readable_or_writable(
        self, initialized_dir: Path, name: str
    ) -> None:
        path = initialized_dir / ".docai" / name
        path.chmod(stat.S_IXUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                startup()
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == (
                f"No read/write permission on state artifact: {path}"
            )
        finally:
            path.chmod(stat.S_IRWXU)


class TestStartupNotInitialized:
    @pytest.mark.integration
    def test_raises_when_docai_dir_missing(self, project_dir: Path) -> None:
        docai = project_dir / ".docai"
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_NOT_INITIALIZED"
        assert exc_info.value.message == (
            f"State directory not found: {docai}. Run 'docai init' first."
        )

    @pytest.mark.integration
    @pytest.mark.parametrize("name", ["version", "purposes.json", "graph.json", "status.json"])
    def test_raises_when_file_artifact_missing(
        self, initialized_dir: Path, name: str
    ) -> None:
        path = initialized_dir / ".docai" / name
        path.unlink()
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_NOT_INITIALIZED"
        assert exc_info.value.message == (
            f"State artifact missing: {path}. Run 'docai init' first."
        )

    @pytest.mark.integration
    @pytest.mark.parametrize("name", ["analyses", "docs"])
    def test_raises_when_dir_artifact_missing(
        self, initialized_dir: Path, name: str
    ) -> None:
        path = initialized_dir / ".docai" / name
        path.rmdir()
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_NOT_INITIALIZED"
        assert exc_info.value.message == (
            f"State artifact missing: {path}. Run 'docai init' first."
        )


class TestStartupCorrupt:
    @pytest.mark.integration
    @pytest.mark.parametrize("name", ["version", "purposes.json", "graph.json", "status.json"])
    def test_raises_when_file_artifact_is_directory(
        self, initialized_dir: Path, name: str
    ) -> None:
        path = initialized_dir / ".docai" / name
        path.unlink()
        path.mkdir()
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_CORRUPT"
        assert exc_info.value.message == f"Expected file at {path}, found directory"

    @pytest.mark.integration
    @pytest.mark.parametrize("name", ["analyses", "docs"])
    def test_raises_when_dir_artifact_is_file(
        self, initialized_dir: Path, name: str
    ) -> None:
        path = initialized_dir / ".docai" / name
        path.rmdir()
        path.touch()
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_CORRUPT"
        assert exc_info.value.message == f"Expected directory at {path}, found file"


class TestStartupVersion:
    @pytest.mark.integration
    def test_raises_on_version_mismatch(self, initialized_dir: Path) -> None:
        (initialized_dir / ".docai" / "version").write_text("999")
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_VERSION_MISMATCH"
        assert exc_info.value.message == (
            f"State version mismatch: expected '{STATE_VERSION}', found '999'"
        )


class TestStartupTmpCleanup:
    @pytest.mark.integration
    def test_deletes_tmp_files_and_logs_warning(self, initialized_dir: Path) -> None:
        tmp_file = initialized_dir / ".docai" / "purposes.json.tmp"
        tmp_file.write_text("partial")
        with patch("docai.state.logger") as mock_logger:
            startup()
        assert not tmp_file.exists()
        mock_logger.warning.assert_called_once_with(
            "[State] Removed incomplete write: '%s'", tmp_file
        )

    @pytest.mark.integration
    def test_no_warning_when_no_tmp_files(self, initialized_dir: Path) -> None:
        with patch("docai.state.logger") as mock_logger:
            startup()
        mock_logger.warning.assert_not_called()


class TestStartupLockfile:
    @pytest.mark.integration
    def test_creates_lock_with_current_pid_when_no_lock_exists(
        self, initialized_dir: Path
    ) -> None:
        startup()
        lock = initialized_dir / ".docai" / "lock"
        assert lock.read_text().strip() == str(os.getpid())

    @pytest.mark.integration
    def test_raises_when_lock_has_alive_pid(self, initialized_dir: Path) -> None:
        pid = os.getpid()
        (initialized_dir / ".docai" / "lock").write_text(str(pid))
        with pytest.raises(StateError) as exc_info:
            startup()
        assert exc_info.value.code == "STATE_LOCKED"
        assert exc_info.value.message == (
            f"Another docai process (PID {pid}) is already running."
        )

    @pytest.mark.integration
    def test_overwrites_lock_and_logs_warning_when_lock_has_dead_pid(
        self, initialized_dir: Path
    ) -> None:
        dead_pid = 99999999
        (initialized_dir / ".docai" / "lock").write_text(str(dead_pid))
        with patch("docai.state.os.kill", side_effect=ProcessLookupError):
            with patch("docai.state.logger") as mock_logger:
                startup()
        lock = initialized_dir / ".docai" / "lock"
        assert lock.read_text().strip() == str(os.getpid())
        mock_logger.warning.assert_called_once_with(
            "[State] Stale lock file found (PID %d no longer running), overwriting.",
            dead_pid,
        )
