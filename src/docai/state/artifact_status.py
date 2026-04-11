from __future__ import annotations

import json
from pathlib import Path

from docai.discovery.datatypes import FileManifest, PackageManifest
from docai.state._io import _atomic_write
from docai.state.datatypes import ArtifactStatus, GenerationStatus
from docai.state.errors import StateError


def get_status() -> dict[str, ArtifactStatus]:
    path = Path.cwd() / ".docai" / "status.json"
    try:
        raw = path.read_text()
    except PermissionError as exc:
        raise StateError(
            message=f"No read permission on state artifact: {path}",
            code="STATE_PERMISSION_DENIED",
        ) from exc
    try:
        data = json.loads(raw)
        return {key: ArtifactStatus.model_validate(value) for key, value in data.items()}
    except Exception as exc:
        raise StateError(
            message=f"State artifact corrupted: {path}",
            code="STATE_CORRUPT",
        ) from exc


def set_status(statuses: dict[str, ArtifactStatus]) -> None:
    path = Path.cwd() / ".docai" / "status.json"
    content = json.dumps({key: value.model_dump() for key, value in statuses.items()})
    _atomic_write(path, content)


def purge_removed() -> None:
    current = get_status()
    set_status({path: entry for path, entry in current.items() if entry.status != GenerationStatus.remove})


def change_status(path: str, status: GenerationStatus, error: str | None = None) -> None:
    current = get_status()
    if path not in current:
        raise StateError(
            message=f"Status entry not found: {path}",
            code="STATE_ENTRY_NOT_FOUND",
        )
    current[path] = ArtifactStatus(
        status=status,
        content_hash=current[path].content_hash,
        error=error,
    )
    set_status(current)


def reconcile_status(file_manifest: FileManifest, package_manifest: PackageManifest) -> list[str]:
    current = get_status()
    new: dict[str, ArtifactStatus] = {}

    for path, entry in file_manifest.items():
        if entry.content_hash is None:
            continue
        if path in current:
            existing = current[path]
            if existing.content_hash != entry.content_hash:
                new[path] = ArtifactStatus(
                    status=GenerationStatus.deprecated,
                    content_hash=entry.content_hash,
                    error=None,
                )
            elif existing.status == GenerationStatus.failed:
                new[path] = ArtifactStatus(
                    status=GenerationStatus.pending,
                    content_hash=entry.content_hash,
                    error=None,
                )
            elif existing.status == GenerationStatus.remove:
                new[path] = ArtifactStatus(
                    status=GenerationStatus.deprecated,
                    content_hash=entry.content_hash,
                    error=None,
                )
            else:
                new[path] = existing
        else:
            new[path] = ArtifactStatus(
                status=GenerationStatus.pending,
                content_hash=entry.content_hash,
                error=None,
            )

    for path, entry in package_manifest.items():
        pkg_hash = entry.content_hash()
        if path in current:
            existing = current[path]
            if existing.content_hash != pkg_hash:
                new[path] = ArtifactStatus(
                    status=GenerationStatus.deprecated,
                    content_hash=pkg_hash,
                    error=None,
                )
            elif existing.status == GenerationStatus.failed:
                new[path] = ArtifactStatus(
                    status=GenerationStatus.pending,
                    content_hash=pkg_hash,
                    error=None,
                )
            elif existing.status == GenerationStatus.remove:
                new[path] = ArtifactStatus(
                    status=GenerationStatus.deprecated,
                    content_hash=pkg_hash,
                    error=None,
                )
            else:
                new[path] = existing
        else:
            new[path] = ArtifactStatus(
                status=GenerationStatus.pending,
                content_hash=pkg_hash,
                error=None,
            )

    tracked = set(new)
    removed: list[str] = []
    for path, existing in current.items():
        if path not in tracked:
            new[path] = ArtifactStatus(
                status=GenerationStatus.remove,
                content_hash=existing.content_hash,
                error=None,
            )
            removed.append(path)

    set_status(new)
    return removed
