from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class GenerationStatus(str, Enum):
    pending = "pending"
    complete = "complete"
    deprecated = "deprecated"
    failed = "failed"
    remove = "remove"


class ArtifactStatus(BaseModel):
    status: GenerationStatus
    content_hash: str
    error: str | None
