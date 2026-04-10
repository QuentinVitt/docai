import hashlib
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from docai.discovery.datatypes import (
    AssetSummary,
    DirectoryEntry,
    FileClassification,
    FileOverride,
)
from docai.discovery.errors import DiscoveryError
from docai.discovery.ignore_rules import IgnoreRules
from docai.discovery.walker import Walker


@pytest.fixture
def ignore_rules() -> IgnoreRules:
    return IgnoreRules([])


@pytest.mark.unit
class TestWalkerConstruction:
    def test_constructs_with_defaults(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        walker = Walker(root=tmp_path, ignore_rules=ignore_rules)
        assert isinstance(walker, Walker)

    def test_stores_root(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        walker = Walker(root=tmp_path, ignore_rules=ignore_rules)
        assert walker.root == tmp_path

    def test_stores_ignore_rules(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        walker = Walker(root=tmp_path, ignore_rules=ignore_rules)
        assert walker.ignore_rules is ignore_rules

    def test_stores_asset_package_threshold(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        walker = Walker(root=tmp_path, ignore_rules=ignore_rules, asset_package_threshold=10)
        assert walker.asset_package_threshold == 10

    def test_default_asset_package_threshold_is_5(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        walker = Walker(root=tmp_path, ignore_rules=ignore_rules)
        assert walker.asset_package_threshold == 5

    def test_threshold_of_1_is_valid(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        walker = Walker(root=tmp_path, ignore_rules=ignore_rules, asset_package_threshold=1)
        assert walker.asset_package_threshold == 1


@pytest.mark.unit
class TestWalkerInvalidThreshold:
    def test_threshold_zero_raises_discovery_error(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        with pytest.raises(DiscoveryError) as exc_info:
            Walker(root=tmp_path, ignore_rules=ignore_rules, asset_package_threshold=0)
        assert exc_info.value.code == "DISCOVERY_INVALID_CONFIG"

    def test_threshold_negative_raises_discovery_error(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        with pytest.raises(DiscoveryError) as exc_info:
            Walker(root=tmp_path, ignore_rules=ignore_rules, asset_package_threshold=-1)
        assert exc_info.value.code == "DISCOVERY_INVALID_CONFIG"

    def test_threshold_zero_exact_message(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        with pytest.raises(DiscoveryError) as exc_info:
            Walker(root=tmp_path, ignore_rules=ignore_rules, asset_package_threshold=0)
        assert exc_info.value.message == "asset_package_threshold must be a positive integer, got 0"

    def test_threshold_negative_five_exact_message(self, tmp_path: Path, ignore_rules: IgnoreRules) -> None:
        with pytest.raises(DiscoveryError) as exc_info:
            Walker(root=tmp_path, ignore_rules=ignore_rules, asset_package_threshold=-5)
        assert exc_info.value.message == "asset_package_threshold must be a positive integer, got -5"


@pytest.mark.unit
class TestBuildPackageEntry:
    @pytest.fixture
    def walker(self, tmp_path: Path) -> Walker:
        return Walker(root=tmp_path, ignore_rules=IgnoreRules([]))

    def test_empty_assets_gives_none(self, walker: Walker) -> None:
        entry = walker._build_package_entry(
            owned_files=[], owned_assets=[], child_packages=[]
        )
        assert entry.assets is None

    def test_owned_files_passed_through(self, walker: Walker) -> None:
        entry = walker._build_package_entry(
            owned_files=["src/main.py", "src/utils.py"],
            owned_assets=[],
            child_packages=[],
        )
        assert entry.files == ["src/main.py", "src/utils.py"]

    def test_child_packages_passed_through(self, walker: Walker) -> None:
        entry = walker._build_package_entry(
            owned_files=[],
            owned_assets=[],
            child_packages=["src/core", "src/api"],
        )
        assert entry.child_packages == ["src/core", "src/api"]

    def test_single_asset_produces_summary(self, walker: Walker, tmp_path: Path) -> None:
        entry = walker._build_package_entry(
            owned_files=[],
            owned_assets=[tmp_path / "logo.png"],
            child_packages=[],
        )
        assert entry.assets == AssetSummary(count=1, types={"png": 1})

    def test_multiple_assets_same_extension_aggregated(self, walker: Walker, tmp_path: Path) -> None:
        entry = walker._build_package_entry(
            owned_files=[],
            owned_assets=[
                tmp_path / "a.png",
                tmp_path / "b.png",
                tmp_path / "c.png",
            ],
            child_packages=[],
        )
        assert entry.assets == AssetSummary(count=3, types={"png": 3})

    def test_mixed_extensions_counted_separately(self, walker: Walker, tmp_path: Path) -> None:
        entry = walker._build_package_entry(
            owned_files=[],
            owned_assets=[
                tmp_path / "a.png",
                tmp_path / "b.png",
                tmp_path / "icon.svg",
            ],
            child_packages=[],
        )
        assert entry.assets == AssetSummary(count=3, types={"png": 2, "svg": 1})

    def test_asset_count_equals_number_of_assets(self, walker: Walker, tmp_path: Path) -> None:
        assets = [tmp_path / f"file{i}.jpg" for i in range(7)]
        entry = walker._build_package_entry(
            owned_files=[], owned_assets=assets, child_packages=[]
        )
        assert entry.assets is not None
        assert entry.assets.count == 7

    def test_extension_stored_without_leading_dot(self, walker: Walker, tmp_path: Path) -> None:
        entry = walker._build_package_entry(
            owned_files=[],
            owned_assets=[tmp_path / "image.png"],
            child_packages=[],
        )
        assert entry.assets is not None
        assert "png" in entry.assets.types
        assert ".png" not in entry.assets.types

    def test_all_collections_empty(self, walker: Walker) -> None:
        entry = walker._build_package_entry(
            owned_files=[], owned_assets=[], child_packages=[]
        )
        assert entry == DirectoryEntry(child_packages=[], files=[], assets=None)

    def test_all_collections_populated(self, walker: Walker, tmp_path: Path) -> None:
        entry = walker._build_package_entry(
            owned_files=["src/main.py"],
            owned_assets=[tmp_path / "logo.png", tmp_path / "icon.svg"],
            child_packages=["src/core"],
        )
        assert entry == DirectoryEntry(
            child_packages=["src/core"],
            files=["src/main.py"],
            assets=AssetSummary(count=2, types={"png": 1, "svg": 1}),
        )


# ── Walker.walk() tests ───────────────────────────────────────────────────────


@pytest.mark.integration
class TestWalkErrorCases:
    def test_root_not_found_raises_error(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        with pytest.raises(DiscoveryError) as exc_info:
            Walker(root=nonexistent, ignore_rules=IgnoreRules([]))
        assert exc_info.value.code == "DISCOVERY_ROOT_NOT_FOUND"
        assert exc_info.value.message == f"Root directory does not exist: '{nonexistent}'"

    def test_root_not_a_directory_raises_error(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")
        with pytest.raises(DiscoveryError) as exc_info:
            Walker(root=file_path, ignore_rules=IgnoreRules([]))
        assert exc_info.value.code == "DISCOVERY_ROOT_NOT_A_DIRECTORY"
        assert exc_info.value.message == f"Root path is not a directory: '{file_path}'"

    def test_unreadable_subdirectory_raises_error(self, tmp_path: Path) -> None:
        subdir = tmp_path / "secret"
        subdir.mkdir()
        subdir.chmod(0o000)
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        try:
            with pytest.raises(DiscoveryError) as exc_info:
                walker.walk()
            assert exc_info.value.code == "DISCOVERY_PERMISSION_DENIED"
            assert exc_info.value.message == "Permission denied reading directory: 'secret'"
        finally:
            subdir.chmod(0o755)


@pytest.mark.integration
class TestWalkBasicClassification:
    def test_empty_root_returns_empty_results(self, tmp_path: Path) -> None:
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, packages, pruned = walker.walk()
        assert manifest == {}
        assert packages == {}
        assert pruned == set()

    def test_python_file_classified_as_processed(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hello')")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert "main.py" in manifest
        assert manifest["main.py"].classification == FileClassification.processed
        assert manifest["main.py"].language == "python"

    def test_markdown_file_classified_as_documentation(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert "README.md" in manifest
        assert manifest["README.md"].classification == FileClassification.documentation
        assert manifest["README.md"].content_hash is None

    def test_asset_file_classified_as_asset(self, tmp_path: Path) -> None:
        (tmp_path / "image.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert "image.png" in manifest
        assert manifest["image.png"].classification == FileClassification.asset
        assert manifest["image.png"].content_hash is None

    def test_nested_file_path_is_relative_posix_string(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("content")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert "src/main.py" in manifest


@pytest.mark.integration
class TestWalkContentHash:
    def test_processed_file_has_sha256_hash(self, tmp_path: Path) -> None:
        content = b"print('hello')"
        (tmp_path / "main.py").write_bytes(content)
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert manifest["main.py"].content_hash == hashlib.sha256(content).hexdigest()

    def test_documentation_file_has_no_hash(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert manifest["README.md"].content_hash is None

    def test_asset_file_has_no_hash(self, tmp_path: Path) -> None:
        (tmp_path / "image.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        manifest, _, _ = walker.walk()
        assert manifest["image.png"].content_hash is None


@pytest.mark.integration
class TestWalkPruning:
    def test_pruned_directory_added_to_pruned_set(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules(["node_modules/"]))
        _, _, pruned = walker.walk()
        assert "node_modules" in pruned

    def test_files_inside_pruned_directory_not_in_manifest(self, tmp_path: Path) -> None:
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        (node_modules / "index.js").write_text("module.exports = {}")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules(["node_modules/"]))
        manifest, _, _ = walker.walk()
        assert "node_modules/index.js" not in manifest


@pytest.mark.integration
class TestWalkSymlinks:
    def test_symlink_file_not_in_manifest(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        target = tmp_path / "target.py"
        target.write_text("content")
        link = tmp_path / "link.py"
        link.symlink_to(target)
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        with caplog.at_level(logging.WARNING, logger="docai.discovery.walker"):
            manifest, _, _ = walker.walk()
        assert "link.py" not in manifest
        assert any(r.message == "[Discovery] Symlink ignored: 'link.py'" for r in caplog.records)

    def test_symlink_directory_not_in_pruned_set(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        target_dir = tmp_path / "target_dir"
        target_dir.mkdir()
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(target_dir)
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        with caplog.at_level(logging.WARNING, logger="docai.discovery.walker"):
            _, _, pruned = walker.walk()
        assert "link_dir" not in pruned
        assert any(r.message == "[Discovery] Symlink ignored: 'link_dir'" for r in caplog.records)


@pytest.mark.integration
class TestWalkSkippedFiles:
    def test_classify_oserror_skips_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "main.py").write_text("content")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        with patch("docai.discovery.walker.classify", side_effect=OSError("read error")):
            with caplog.at_level(logging.WARNING, logger="docai.discovery.walker"):
                manifest, _, _ = walker.walk()
        assert "main.py" not in manifest
        assert any(
            r.message == "[Discovery] Could not read file, skipping: 'main.py'" for r in caplog.records
        )

    def test_hash_read_failure_skips_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "main.py").write_text("content")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        with patch(
            "docai.discovery.walker.classify",
            return_value=("python", FileClassification.processed),
        ):
            with patch.object(Path, "read_bytes", side_effect=OSError("I/O error")):
                with caplog.at_level(logging.WARNING, logger="docai.discovery.walker"):
                    manifest, _, _ = walker.walk()
        assert "main.py" not in manifest
        assert any(
            r.message == "[Discovery] Could not read file for hashing, skipping: 'main.py'"
            for r in caplog.records
        )

    def test_unknown_file_in_manifest_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "mystery").write_text("???")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        with caplog.at_level(logging.WARNING, logger="docai.discovery.walker"):
            manifest, _, _ = walker.walk()
        assert "mystery" in manifest
        assert manifest["mystery"].classification == FileClassification.unknown
        assert manifest["mystery"].content_hash is None
        assert any(
            r.message == "[Discovery] Unknown file type, skipping processing: 'mystery'"
            for r in caplog.records
        )


@pytest.mark.integration
class TestWalkFileOverride:
    def test_excluded_file_has_override_exclude(self, tmp_path: Path) -> None:
        (tmp_path / "secret.log").write_text("logs")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules(["*.log"]))
        manifest, _, _ = walker.walk()
        assert "secret.log" in manifest
        assert manifest["secret.log"].override == FileOverride.exclude

    def test_force_included_non_asset_has_hash(self, tmp_path: Path) -> None:
        content = b"some content"
        (tmp_path / "mystery").write_bytes(content)
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules(["*", "!mystery"]))
        manifest, _, _ = walker.walk()
        assert "mystery" in manifest
        assert manifest["mystery"].override == FileOverride.include
        assert manifest["mystery"].content_hash == hashlib.sha256(content).hexdigest()

    def test_force_included_asset_has_no_hash(self, tmp_path: Path) -> None:
        (tmp_path / "image.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules(["*.png", "!image.png"]))
        manifest, _, _ = walker.walk()
        assert "image.png" in manifest
        assert manifest["image.png"].override == FileOverride.include
        assert manifest["image.png"].content_hash is None


@pytest.mark.integration
class TestWalkPackageQualification:
    def test_directory_with_two_processed_files_is_normal_package(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("pass")
        (src / "b.py").write_text("pass")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        _, packages, _ = walker.walk()
        assert "src" in packages

    def test_directory_with_one_processed_file_is_not_a_package(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("pass")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        _, packages, _ = walker.walk()
        assert "src" not in packages

    def test_directory_with_processed_file_and_child_package_is_normal_package(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("pass")
        core = src / "core"
        core.mkdir()
        (core / "x.py").write_text("pass")
        (core / "y.py").write_text("pass")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        _, packages, _ = walker.walk()
        assert "src" in packages
        assert "src/core" in packages

    def test_directory_meeting_asset_threshold_is_asset_package(
        self, tmp_path: Path
    ) -> None:
        images = tmp_path / "images"
        images.mkdir()
        for i in range(5):
            (images / f"img{i}.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]), asset_package_threshold=5)
        _, packages, _ = walker.walk()
        assert "images" in packages

    def test_directory_below_asset_threshold_is_not_a_package(
        self, tmp_path: Path
    ) -> None:
        images = tmp_path / "images"
        images.mkdir()
        for i in range(4):
            (images / f"img{i}.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]), asset_package_threshold=5)
        _, packages, _ = walker.walk()
        assert "images" not in packages

    def test_directory_with_assets_and_processed_file_is_not_asset_package(
        self, tmp_path: Path
    ) -> None:
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "main.py").write_text("pass")
        for i in range(5):
            (mixed / f"img{i}.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]), asset_package_threshold=5)
        _, packages, _ = walker.walk()
        assert "mixed" not in packages

    def test_root_with_two_processed_files_is_package_under_dot(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "main.py").write_text("pass")
        (tmp_path / "utils.py").write_text("pass")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        _, packages, _ = walker.walk()
        assert "." in packages


@pytest.mark.integration
class TestWalkPromotion:
    def test_non_package_intermediary_files_promoted_to_ancestor(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "main.py").write_text("pass")
        (tmp_path / "utils.py").write_text("pass")
        middleware = tmp_path / "middleware"
        middleware.mkdir()
        (middleware / "handler.py").write_text("pass")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        _, packages, _ = walker.walk()
        assert "." in packages
        assert "middleware/handler.py" in packages["."].files

    def test_non_package_intermediary_assets_promoted_to_ancestor(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "main.py").write_text("pass")
        (tmp_path / "utils.py").write_text("pass")
        icons = tmp_path / "icons"
        icons.mkdir()
        for i in range(4):
            (icons / f"icon{i}.png").write_bytes(b"")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]), asset_package_threshold=5)
        _, packages, _ = walker.walk()
        assert "." in packages
        assert packages["."].assets is not None
        assert packages["."].assets.count == 4

    def test_child_packages_listed_in_parent_entry(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("pass")
        (tmp_path / "utils.py").write_text("pass")
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("pass")
        (src / "b.py").write_text("pass")
        walker = Walker(root=tmp_path, ignore_rules=IgnoreRules([]))
        _, packages, _ = walker.walk()
        assert "." in packages
        assert packages["."].child_packages == ["src"]
