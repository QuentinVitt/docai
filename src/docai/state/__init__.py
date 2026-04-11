from __future__ import annotations

import json
import os
import shutil
from logging import getLogger
from pathlib import Path

from docai.state.errors import StateError

logger = getLogger(__name__)

STATE_VERSION = "1"

_JSON_FILES = ("purposes.json", "graph.json", "status.json")
_FILE_ARTIFACTS = ("version", "purposes.json", "graph.json", "status.json")
_DIR_ARTIFACTS = ("analyses", "docs")


def initialize() -> None:
    cwd = Path.cwd()
    docai = cwd / ".docai"

    if not os.access(cwd, os.R_OK | os.W_OK):
        raise StateError(
            message=f"No read/write permission on project root: {cwd}",
            code="STATE_PERMISSION_DENIED",
        )

    if docai.exists() and not os.access(docai, os.R_OK | os.W_OK):
        raise StateError(
            message=f"No read/write permission on state directory: {docai}",
            code="STATE_PERMISSION_DENIED",
        )

    docai.mkdir(exist_ok=True)

    version_file = docai / "version"
    if not version_file.exists():
        version_file.write_text(STATE_VERSION)

    for filename in _JSON_FILES:
        path = docai / filename
        if not path.exists():
            path.write_text(json.dumps({}))

    for subdir in _DIR_ARTIFACTS:
        (docai / subdir).mkdir(exist_ok=True)


def startup() -> None:
    cwd = Path.cwd()
    docai = cwd / ".docai"

    if not os.access(cwd, os.R_OK | os.W_OK):
        raise StateError(
            message=f"No read/write permission on project root: {cwd}",
            code="STATE_PERMISSION_DENIED",
        )

    if not docai.exists():
        raise StateError(
            message=f"State directory not found: {docai}. Run 'docai init' first.",
            code="STATE_NOT_INITIALIZED",
        )

    if not os.access(docai, os.R_OK | os.W_OK):
        raise StateError(
            message=f"No read/write permission on state directory: {docai}",
            code="STATE_PERMISSION_DENIED",
        )

    for name in _FILE_ARTIFACTS:
        path = docai / name
        if not path.exists():
            raise StateError(
                message=f"State artifact missing: {path}. Run 'docai init' first.",
                code="STATE_NOT_INITIALIZED",
            )
        if not path.is_file():
            raise StateError(
                message=f"Expected file at {path}, found directory",
                code="STATE_CORRUPT",
            )
        if not os.access(path, os.R_OK | os.W_OK):
            raise StateError(
                message=f"No read/write permission on state artifact: {path}",
                code="STATE_PERMISSION_DENIED",
            )

    for name in _DIR_ARTIFACTS:
        path = docai / name
        if not path.exists():
            raise StateError(
                message=f"State artifact missing: {path}. Run 'docai init' first.",
                code="STATE_NOT_INITIALIZED",
            )
        if not path.is_dir():
            raise StateError(
                message=f"Expected directory at {path}, found file",
                code="STATE_CORRUPT",
            )
        if not os.access(path, os.R_OK | os.W_OK):
            raise StateError(
                message=f"No read/write permission on state artifact: {path}",
                code="STATE_PERMISSION_DENIED",
            )

    found = (docai / "version").read_text().strip()
    if found != STATE_VERSION:
        raise StateError(
            message=f"State version mismatch: expected '{STATE_VERSION}', found '{found}'",
            code="STATE_VERSION_MISMATCH",
        )

    for tmp_file in docai.glob("*.tmp"):
        tmp_file.unlink()
        logger.warning("[State] Removed incomplete write: '%s'", tmp_file)

    lock = docai / "lock"
    if lock.exists():
        pid = int(lock.read_text().strip())
        try:
            os.kill(pid, 0)
            raise StateError(
                message=f"Another docai process (PID {pid}) is already running.",
                code="STATE_LOCKED",
            )
        except ProcessLookupError:
            logger.warning(
                "[State] Stale lock file found (PID %d no longer running), overwriting.",
                pid,
            )

    lock.write_text(str(os.getpid()))


def reinitialize() -> None:
    cwd = Path.cwd()
    docai = cwd / ".docai"

    if not os.access(cwd, os.R_OK | os.W_OK):
        raise StateError(
            message=f"No read/write permission on project root: {cwd}",
            code="STATE_PERMISSION_DENIED",
        )

    if docai.exists():
        shutil.rmtree(docai)

    initialize()
