from __future__ import annotations

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
    files: list[str]
    subdirectories: list[str]
    asset_summary: AssetSummary | None


FileManifest = dict[str, ManifestEntry]
DirectoryRegistry = dict[str, DirectoryEntry]
