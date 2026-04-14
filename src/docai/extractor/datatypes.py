from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class FileType(str, Enum):
    source_file = "source_file"
    source_like_config = "source_like_config"
    config_file = "config_file"
    other = "other"


class EntityCategory(str, Enum):
    callable = "callable"
    macro = "macro"
    type = "type"
    value = "value"
    implementation = "implementation"


class Entity(BaseModel):
    category: EntityCategory
    name: str
    kind: str
    parent: str | None
    signature: str | None


class FileAnalysis(BaseModel):
    file_path: str
    file_type: FileType
    entities: list[Entity]
    dependencies: list[str]
