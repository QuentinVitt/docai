from __future__ import annotations

from pathlib import Path

from docai.state.errors import StateError


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content)
        tmp.rename(path)
    except PermissionError as exc:
        raise StateError(
            message=f"No write permission on state artifact: {path}",
            code="STATE_PERMISSION_DENIED",
        ) from exc
