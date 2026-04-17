from __future__ import annotations

from pathlib import Path

from docai.extractor.datatypes import FileAnalysis
from docai.state.artifact_status import get_status
from docai.state.datatypes import GenerationStatus
from docai.state.errors import StateError

_PURGE_STATUSES = {GenerationStatus.deprecated, GenerationStatus.remove}


def purge_analyses() -> None:
    analyses_dir = Path.cwd() / ".docai" / "analyses"

    try:
        statuses = get_status()
    except StateError as exc:
        raise StateError(
            message="Analysis purge failed",
            code="STATE_PURGE_FAILED",
        ) from exc

    for analysis_file in sorted(analyses_dir.rglob("*.json"), reverse=True):
        rel = analysis_file.relative_to(analyses_dir)
        file_path = str(rel)[: -len(".json")]  # strip trailing .json
        status_entry = statuses.get(file_path)
        should_delete = status_entry is None or status_entry.status in _PURGE_STATUSES
        if should_delete:
            try:
                analysis_file.unlink()
            except PermissionError as exc:
                raise StateError(
                    message=f"Analysis purge failed: permission denied on {analysis_file}",
                    code="STATE_PURGE_FAILED",
                ) from exc

    # Remove empty directories bottom-up
    for dirpath in sorted(analyses_dir.rglob("*"), reverse=True):
        if dirpath.is_dir() and dirpath != analyses_dir:
            try:
                dirpath.rmdir()  # only succeeds if empty
            except OSError:
                pass  # not empty, leave it


def save_analysis(analysis: FileAnalysis) -> None:
    path = Path.cwd() / ".docai" / "analyses" / (analysis.file_path + ".json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise StateError(
            message=f"No write permission on state artifact: {path}",
            code="STATE_PERMISSION_DENIED",
        ) from exc
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(analysis.model_dump_json())
        tmp.rename(path)
    except PermissionError as exc:
        raise StateError(
            message=f"No write permission on state artifact: {path}",
            code="STATE_PERMISSION_DENIED",
        ) from exc


def get_analysis(file_path: str) -> FileAnalysis | None:
    path = Path.cwd() / ".docai" / "analyses" / (file_path + ".json")

    if not path.exists():
        return None

    try:
        raw = path.read_text()
    except PermissionError as exc:
        raise StateError(
            message=f"No read permission on state artifact: {path}",
            code="STATE_PERMISSION_DENIED",
        ) from exc

    try:
        return FileAnalysis.model_validate_json(raw)
    except Exception as exc:
        raise StateError(
            message=f"State artifact corrupted: {path}",
            code="STATE_CORRUPT",
        ) from exc
