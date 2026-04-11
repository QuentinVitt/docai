from __future__ import annotations

import stat
from pathlib import Path

import pytest

from docai.discovery.datatypes import (
    AssetSummary,
    DirectoryEntry,
    FileClassification,
    ManifestEntry,
)
from docai.state import initialize
from docai.state.artifact_status import get_status, reconcile_status, set_status
from docai.state.datatypes import ArtifactStatus, GenerationStatus
from docai.state.errors import StateError


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    initialize()
    return tmp_path / ".docai"


def make_file_entry(content_hash: str | None = "abc123") -> ManifestEntry:
    return ManifestEntry(
        classification=FileClassification.processed,
        language="python",
        content_hash=content_hash,
        override=None,
    )


def make_package_entry(
    files: list[str] | None = None,
    child_packages: list[str] | None = None,
) -> DirectoryEntry:
    return DirectoryEntry(
        files=files or ["src/main.py"],
        child_packages=child_packages or [],
        assets=None,
    )


def make_artifact_status(
    status: GenerationStatus,
    content_hash: str = "abc123",
    error: str | None = None,
) -> ArtifactStatus:
    return ArtifactStatus(status=status, content_hash=content_hash, error=error)


class TestFileManifestRules:
    @pytest.mark.integration
    def test_file_not_in_status_added_as_pending(self, state_dir: Path) -> None:
        file_manifest = {"src/main.py": make_file_entry("abc123")}
        reconcile_status(file_manifest, {})
        result = get_status()
        assert result["src/main.py"].status == GenerationStatus.pending
        assert result["src/main.py"].content_hash == "abc123"

    @pytest.mark.integration
    def test_file_same_hash_complete_stays_complete(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.complete, "abc123")})
        reconcile_status({"src/main.py": make_file_entry("abc123")}, {})
        assert get_status()["src/main.py"].status == GenerationStatus.complete

    @pytest.mark.integration
    def test_file_same_hash_pending_stays_pending(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.pending, "abc123")})
        reconcile_status({"src/main.py": make_file_entry("abc123")}, {})
        assert get_status()["src/main.py"].status == GenerationStatus.pending

    @pytest.mark.integration
    def test_file_same_hash_deprecated_stays_deprecated(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.deprecated, "abc123")})
        reconcile_status({"src/main.py": make_file_entry("abc123")}, {})
        assert get_status()["src/main.py"].status == GenerationStatus.deprecated

    @pytest.mark.integration
    def test_file_same_hash_removed_marked_deprecated(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.remove, "abc123")})
        reconcile_status({"src/main.py": make_file_entry("abc123")}, {})
        assert get_status()["src/main.py"].status == GenerationStatus.deprecated

    @pytest.mark.integration
    def test_file_same_hash_failed_reset_to_pending(self, state_dir: Path) -> None:
        set_status({"src/main.py": make_artifact_status(GenerationStatus.failed, "abc123", error="LLM timeout")})
        reconcile_status({"src/main.py": make_file_entry("abc123")}, {})
        result = get_status()["src/main.py"]
        assert result.status == GenerationStatus.pending
        assert result.error is None

    @pytest.mark.integration
    @pytest.mark.parametrize("prior_status", [
        GenerationStatus.pending,
        GenerationStatus.complete,
        GenerationStatus.deprecated,
        GenerationStatus.failed,
        GenerationStatus.remove,
    ])
    def test_file_different_hash_always_marked_deprecated(
        self, state_dir: Path, prior_status: GenerationStatus
    ) -> None:
        set_status({"src/main.py": make_artifact_status(prior_status, "old_hash")})
        reconcile_status({"src/main.py": make_file_entry("new_hash")}, {})
        assert get_status()["src/main.py"].status == GenerationStatus.deprecated


class TestPackageManifestRules:
    @pytest.mark.integration
    def test_package_not_in_status_added_as_pending(self, state_dir: Path) -> None:
        entry = make_package_entry()
        reconcile_status({}, {"src": entry})
        result = get_status()
        assert result["src"].status == GenerationStatus.pending
        assert result["src"].content_hash == entry.content_hash()

    @pytest.mark.integration
    def test_package_same_hash_complete_stays_complete(self, state_dir: Path) -> None:
        entry = make_package_entry()
        set_status({"src": make_artifact_status(GenerationStatus.complete, entry.content_hash())})
        reconcile_status({}, {"src": entry})
        assert get_status()["src"].status == GenerationStatus.complete

    @pytest.mark.integration
    def test_package_same_hash_failed_reset_to_pending(self, state_dir: Path) -> None:
        entry = make_package_entry()
        set_status({"src": make_artifact_status(GenerationStatus.failed, entry.content_hash(), error="LLM timeout")})
        reconcile_status({}, {"src": entry})
        result = get_status()["src"]
        assert result.status == GenerationStatus.pending
        assert result.error is None

    @pytest.mark.integration
    def test_package_different_hash_marked_deprecated(self, state_dir: Path) -> None:
        entry = make_package_entry()
        set_status({"src": make_artifact_status(GenerationStatus.complete, "old_hash")})
        reconcile_status({}, {"src": entry})
        assert get_status()["src"].status == GenerationStatus.deprecated


class TestCrossManifest:
    @pytest.mark.integration
    def test_status_entry_absent_from_both_manifests_marked_removed(
        self, state_dir: Path
    ) -> None:
        set_status({"src/gone.py": make_artifact_status(GenerationStatus.complete, "abc123")})
        reconcile_status({}, {})
        assert get_status()["src/gone.py"].status == GenerationStatus.remove

    @pytest.mark.integration
    def test_returns_removed_paths(self, state_dir: Path) -> None:
        set_status({"src/gone.py": make_artifact_status(GenerationStatus.complete, "abc123")})
        removed = reconcile_status({}, {})
        assert removed == ["src/gone.py"]

    @pytest.mark.integration
    def test_returns_empty_list_when_no_removed_paths(self, state_dir: Path) -> None:
        removed = reconcile_status({"src/main.py": make_file_entry("abc123")}, {})
        assert removed == []

    @pytest.mark.integration
    def test_returns_all_removed_paths(self, state_dir: Path) -> None:
        set_status({
            "src/a.py": make_artifact_status(GenerationStatus.complete, "abc123"),
            "src/b.py": make_artifact_status(GenerationStatus.complete, "def456"),
        })
        removed = reconcile_status({}, {})
        assert sorted(removed) == ["src/a.py", "src/b.py"]

    @pytest.mark.integration
    def test_file_and_package_entries_both_correctly_reconciled(
        self, state_dir: Path
    ) -> None:
        pkg = make_package_entry()
        reconcile_status(
            {"src/main.py": make_file_entry("abc123")},
            {"src": pkg},
        )
        result = get_status()
        assert result["src/main.py"].status == GenerationStatus.pending
        assert result["src"].status == GenerationStatus.pending


class TestEdgeCases:
    @pytest.mark.integration
    def test_file_with_none_hash_not_tracked(self, state_dir: Path) -> None:
        file_manifest = {"README.md": make_file_entry(content_hash=None)}
        reconcile_status(file_manifest, {})
        assert "README.md" not in get_status()

    @pytest.mark.integration
    def test_both_manifests_empty_existing_entries_marked_removed(
        self, state_dir: Path
    ) -> None:
        set_status({
            "src/main.py": make_artifact_status(GenerationStatus.complete, "abc123"),
            "src": make_artifact_status(GenerationStatus.complete, "def456"),
        })
        reconcile_status({}, {})
        result = get_status()
        assert result["src/main.py"].status == GenerationStatus.remove
        assert result["src"].status == GenerationStatus.remove

    @pytest.mark.integration
    def test_both_manifests_empty_status_empty_stays_empty(self, state_dir: Path) -> None:
        removed = reconcile_status({}, {})
        assert get_status() == {}
        assert removed == []


class TestErrorPropagation:
    @pytest.mark.integration
    def test_unreadable_status_raises_state_permission_denied(
        self, state_dir: Path
    ) -> None:
        path = state_dir / "status.json"
        path.chmod(stat.S_IWUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                reconcile_status({}, {})
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.integration
    def test_unwritable_docai_raises_state_permission_denied(
        self, state_dir: Path
    ) -> None:
        state_dir.chmod(stat.S_IXUSR | stat.S_IRUSR)
        try:
            with pytest.raises(StateError) as exc_info:
                reconcile_status({}, {})
            assert exc_info.value.code == "STATE_PERMISSION_DENIED"
        finally:
            state_dir.chmod(stat.S_IRWXU)
