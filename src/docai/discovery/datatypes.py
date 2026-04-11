from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel


class FileClassification(str, Enum):
    processed = "processed"
    documentation = "documentation"
    asset = "asset"
    ignored = "ignored"
    unknown = "unknown"


class FileOverride(str, Enum):
    include = "include"
    exclude = "exclude"


class ManifestEntry(BaseModel):
    classification: FileClassification
    language: str | None
    content_hash: str | None
    override: FileOverride | None


class AssetSummary(BaseModel):
    count: int
    types: dict[str, int]


class DirectoryEntry(BaseModel):
    child_packages: list[str]
    files: list[str]
    assets: AssetSummary | None

    def content_hash(self) -> str:
        data = self.model_dump()
        data["files"] = sorted(data["files"])
        data["child_packages"] = sorted(data["child_packages"])
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


FileManifest = dict[str, ManifestEntry]
PackageManifest = dict[str, DirectoryEntry]
