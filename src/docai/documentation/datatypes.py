from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class Parameter(BaseModel):
    """An input parameter of a callable."""

    name: str
    type_hint: Optional[str] = None
    description: str


class Attribute(BaseModel):
    """A field or attribute on a class or datatype."""

    name: str
    type_hint: Optional[str] = None
    description: str


class ReturnValue(BaseModel):
    """The return value of a callable."""

    type_hint: Optional[str] = None
    description: str


class RaisesEntry(BaseModel):
    """An exception that a callable may raise."""

    exception: str
    description: str


# ---------------------------------------------------------------------------
# Item level — individual code elements within a file
# ---------------------------------------------------------------------------


class DocItemType(Enum):
    FUNCTION = "function"
    METHOD = "method"  # function belonging to a class
    CLASS = "class"
    DATATYPE = "datatype"  # dataclass, TypedDict, named tuple, struct, etc.
    CONSTANT = "constant"


class DocItem(BaseModel):
    """Documentation for a single code element (function, class, etc.)."""

    name: str
    type: DocItemType
    description: str

    # For METHOD: name of the containing class; None for top-level items.
    parent: Optional[str] = None

    # Callables (FUNCTION, METHOD)
    parameters: list[Parameter] = []
    returns: Optional[ReturnValue] = None
    raises: list[RaisesEntry] = []
    side_effects: Optional[str] = None  # prose description

    # Classes and datatypes
    attributes: list[Attribute] = []
    dunder_methods: list[str] = []  # e.g. ["__str__", "__repr__", "__eq__"]


# ---------------------------------------------------------------------------
# File level
# ---------------------------------------------------------------------------


class FileDocType(Enum):
    CODE = "code"  # .py, .js, .ts, ... — contains DocItems
    CONFIG = "config"  # .yaml, .json, .toml, .ini, ...
    DOCS = "docs"  # .md, .rst, .txt, ...
    OTHER = "other"  # any other human-authored text file
    SKIPPED = "skipped"  # binary, generated, or lock files — not documented


class FileDoc(BaseModel):
    """Documentation for a single file."""

    path: str
    type: FileDocType
    description: str  # empty string for SKIPPED
    items: list[DocItem] = []  # populated only for CODE files


# ---------------------------------------------------------------------------
# Package level
# ---------------------------------------------------------------------------


class PackageDoc(BaseModel):
    """Documentation for a directory / package."""

    path: str
    description: str
    files: list[str] = []  # paths of direct FileDoc children
    packages: list[str] = []  # paths of direct PackageDoc children


# ---------------------------------------------------------------------------
# Project level
# ---------------------------------------------------------------------------


class ProjectDoc(BaseModel):
    """Top-level documentation for an entire project."""

    name: str
    description: str
    packages: list[str] = []  # paths of top-level PackageDoc children


# ---------------------------------------------------------------------------
#  Config
# ---------------------------------------------------------------------------


class DocumentationCacheConfig(BaseModel):
    """Configuration for the documentation disk cache."""

    cache_dir: str
    use_cache: bool = True
    start_with_clean_cache: bool = False
    max_disk_size: int = 1_000_000_000  # bytes; evicts oldest entries first
    max_age: float = 86_400             # seconds; entries older than this are stale
    max_ram_size: Optional[int] = None  # max items in RAM cache; None = unlimited
