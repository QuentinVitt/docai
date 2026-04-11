from __future__ import annotations

import stat
from pathlib import Path

import pytest

from docai.state._io import _atomic_write
from docai.state.errors import StateError


@pytest.fixture
def target(tmp_path: Path) -> Path:
    return tmp_path / "status.json"


class TestAtomicWriteHappyPath:
    @pytest.mark.integration
    def test_creates_file_with_exact_content(self, target: Path) -> None:
        _atomic_write(target, '{"key": "value"}')
        assert target.read_text() == '{"key": "value"}'

    @pytest.mark.integration
    def test_overwrites_existing_file(self, target: Path) -> None:
        target.write_text("old content")
        _atomic_write(target, "new content")
        assert target.read_text() == "new content"

    @pytest.mark.integration
    def test_no_tmp_file_remains_after_success(self, target: Path) -> None:
        _atomic_write(target, "content")
        tmp = target.with_suffix(target.suffix + ".tmp")
        assert not tmp.exists()


class TestAtomicWriteErrors:
    @pytest.mark.integration
    def test_raises_state_error_when_directory_not_writable(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "status.json"
        tmp_path.chmod(stat.S_IXUSR | stat.S_IRUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                _atomic_write(target, "content")
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
            assert exc_info.value.message == f"No write permission on state artifact: {target}"
            assert isinstance(exc_info.value.__cause__, PermissionError)
        finally:
            tmp_path.chmod(stat.S_IRWXU)
