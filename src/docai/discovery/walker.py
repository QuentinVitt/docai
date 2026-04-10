from __future__ import annotations

import hashlib
import logging
from collections import deque
from pathlib import Path

from docai.discovery.classifier import classify
from docai.discovery.datatypes import (
    AssetSummary,
    DirectoryEntry,
    FileClassification,
    FileManifest,
    FileOverride,
    ManifestEntry,
    PackageManifest,
)
from docai.discovery.errors import DiscoveryError
from docai.discovery.ignore_rules import IgnoreRules

logger = logging.getLogger(__name__)


class Walker:
    def __init__(
        self,
        root: Path,
        ignore_rules: IgnoreRules,
        asset_package_threshold: int = 5,
    ) -> None:
        if asset_package_threshold < 1:
            raise DiscoveryError(
                message=f"asset_package_threshold must be a positive integer, got {asset_package_threshold}",
                code="DISCOVERY_INVALID_CONFIG",
            )
        self.root = root
        if not self.root.exists():
            raise DiscoveryError(
                message=f"Root directory does not exist: '{self.root}'",
                code="DISCOVERY_ROOT_NOT_FOUND",
            )
        if not self.root.is_dir():
            raise DiscoveryError(
                message=f"Root path is not a directory: '{self.root}'",
                code="DISCOVERY_ROOT_NOT_A_DIRECTORY",
            )

        self.ignore_rules = ignore_rules
        self.asset_package_threshold = asset_package_threshold

    def _build_package_entry(
        self,
        owned_files: list[str],
        owned_assets: list[Path],
        child_packages: list[str],
    ) -> DirectoryEntry:
        if not owned_assets:
            assets = None
        else:
            types: dict[str, int] = {}
            for asset in owned_assets:
                ext = asset.suffix.lstrip(".")
                types[ext] = types.get(ext, 0) + 1
            assets = AssetSummary(count=len(owned_assets), types=types)
        return DirectoryEntry(
            child_packages=child_packages,
            files=owned_files,
            assets=assets,
        )

    def walk(self) -> tuple[FileManifest, PackageManifest, set[str]]:

        # change here: moved root directory checks into __init__

        file_manifest: FileManifest = {}
        pruned: set[str] = set()

        # Per-directory data collected during BFS traversal.
        # Keys are relative POSIX path strings ("." for root).
        dir_processed_files: dict[str, list[str]] = {}
        dir_non_asset_files: dict[str, list[str]] = {}
        dir_asset_files: dict[str, list[Path]] = {}
        dir_children: dict[str, list[str]] = {}
        traversal_order: list[str] = []

        queue: deque[Path] = deque([self.root])
        while queue:
            current = queue.popleft()
            rel = current.relative_to(self.root)
            rel_posix = rel.as_posix()

            traversal_order.append(rel_posix)
            dir_processed_files[rel_posix] = []
            dir_non_asset_files[rel_posix] = []
            dir_asset_files[rel_posix] = []
            dir_children[rel_posix] = []

            try:
                entries = sorted(current.iterdir())
            except PermissionError:
                raise DiscoveryError(
                    message=f"Permission denied reading directory: '{rel_posix}'",
                    code="DISCOVERY_PERMISSION_DENIED",
                )

            for entry in entries:
                if (  # change here: include force included symlinks
                    entry.is_symlink()
                    and self.ignore_rules.file_override(entry.relative_to(self.root))
                    != FileOverride.include
                ):
                    rel_entry_posix = entry.relative_to(self.root).as_posix()
                    logger.warning("[Discovery] Symlink ignored: '%s'", rel_entry_posix)
                    continue

                if entry.is_dir():
                    rel_entry_path = entry.relative_to(self.root)
                    if self.ignore_rules.should_prune_directory(rel_entry_path):
                        pruned.add(rel_entry_path.as_posix())
                    else:
                        dir_children[rel_posix].append(rel_entry_path.as_posix())
                        queue.append(entry)
                    continue

                rel_entry_path = entry.relative_to(self.root)
                rel_entry_posix = rel_entry_path.as_posix()
                override = self.ignore_rules.file_override(rel_entry_path)

                try:
                    language, classification = classify(entry)
                except OSError:
                    logger.warning(
                        "[Discovery] Could not read file, skipping: '%s'",
                        rel_entry_posix,
                    )
                    continue

                if classification == FileClassification.unknown:
                    logger.warning(
                        "[Discovery] Unknown file type, skipping processing: '%s'",
                        rel_entry_posix,
                    )

                # change here: excluded processed files also need no hashing
                need_hash = (
                    classification == FileClassification.processed
                    and override != FileOverride.exclude
                ) or (
                    override == FileOverride.include
                    and classification != FileClassification.asset
                )
                content_hash: str | None = None
                if need_hash:
                    try:
                        data = entry.read_bytes()
                        content_hash = hashlib.sha256(data).hexdigest()
                    except OSError:
                        logger.warning(
                            "[Discovery] Could not read file for hashing, skipping: '%s'",
                            rel_entry_posix,
                        )
                        continue

                file_manifest[rel_entry_posix] = ManifestEntry(
                    classification=classification,
                    language=language,
                    content_hash=content_hash,
                    override=override,
                )

                if classification == FileClassification.asset:
                    dir_asset_files[rel_posix].append(entry)
                else:
                    dir_non_asset_files[rel_posix].append(rel_entry_posix)
                    if classification == FileClassification.processed:
                        dir_processed_files[rel_posix].append(rel_entry_posix)

        # Bottom-up package qualification (reverse BFS = leaves first).
        package_manifest: PackageManifest = {}
        is_package: dict[str, bool] = {}
        promoted_non_asset_files: dict[str, list[str]] = {}
        promoted_assets: dict[str, list[Path]] = {}
        promoted_child_packages: dict[str, list[str]] = {}
        scope_has_processed: dict[str, bool] = {}

        for dir_posix in reversed(traversal_order):
            child_packages: list[str] = []
            visible_child_packages: list[str] = []
            accumulated_non_asset_files: list[str] = []
            accumulated_assets: list[Path] = []
            has_processed_from_children = False

            for child_posix in dir_children[dir_posix]:
                if is_package.get(child_posix, False):
                    child_packages.append(child_posix)
                    visible_child_packages.append(child_posix)
                else:
                    accumulated_non_asset_files.extend(
                        promoted_non_asset_files.get(child_posix, [])
                    )
                    accumulated_assets.extend(promoted_assets.get(child_posix, []))
                    visible_child_packages.extend(
                        promoted_child_packages.get(child_posix, [])
                    )
                    has_processed_from_children = (
                        has_processed_from_children
                        or scope_has_processed.get(child_posix, False)
                    )

            all_non_asset_files = (
                dir_non_asset_files[dir_posix] + accumulated_non_asset_files
            )
            all_assets = dir_asset_files[dir_posix] + accumulated_assets
            direct_processed_count = len(dir_processed_files[dir_posix])
            this_has_processed = (
                direct_processed_count > 0 or has_processed_from_children
            )
            scope_has_processed[dir_posix] = this_has_processed

            documentable = direct_processed_count + len(child_packages)
            is_normal = documentable >= 2
            is_asset = (
                not this_has_processed
                and len(child_packages) == 0
                and len(all_assets) >= self.asset_package_threshold
            )

            if is_normal or is_asset:
                is_package[dir_posix] = True
                package_manifest[dir_posix] = self._build_package_entry(
                    owned_files=all_non_asset_files,
                    owned_assets=all_assets,
                    child_packages=visible_child_packages,
                )
            else:
                is_package[dir_posix] = False
                promoted_non_asset_files[dir_posix] = all_non_asset_files
                promoted_assets[dir_posix] = all_assets
                promoted_child_packages[dir_posix] = visible_child_packages

        return file_manifest, package_manifest, pruned
