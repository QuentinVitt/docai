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

    def __str__(self) -> str:
        type_part = f" ({self.type_hint})" if self.type_hint else ""
        return f"{self.name}{type_part}: {self.description}"


class Attribute(BaseModel):
    """A field or attribute on a class or datatype."""

    name: str
    type_hint: Optional[str] = None
    description: str

    def __str__(self) -> str:
        type_part = f" ({self.type_hint})" if self.type_hint else ""
        return f"{self.name}{type_part}: {self.description}"


class ReturnValue(BaseModel):
    """The return value of a callable."""

    type_hint: Optional[str] = None
    description: str

    def __str__(self) -> str:
        type_part = f"({self.type_hint}) " if self.type_hint else ""
        return f"{type_part}{self.description}"


class RaisesEntry(BaseModel):
    """An exception that a callable may raise."""

    exception: str
    description: str

    def __str__(self) -> str:
        return f"{self.exception}: {self.description}"


# ---------------------------------------------------------------------------
# Item level — individual code elements within a file
# ---------------------------------------------------------------------------


class DocItemType(Enum):
    FUNCTION = "function"
    METHOD = "method"  # function belonging to a class
    CLASS = "class"
    DATATYPE = "datatype"  # dataclass, TypedDict, named tuple, struct, etc.
    CONSTANT = "constant"

    def __str__(self) -> str:
        return self.value


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

    def __str__(self) -> str:
        parent_part = f" ({self.parent})" if self.parent else ""
        lines = [
            f"{self.type} {self.name}{parent_part}:",
            f"  {self.description}",
        ]

        if self.type in (DocItemType.FUNCTION, DocItemType.METHOD):
            if self.parameters:
                lines.append("  Parameters:")
                for p in self.parameters:
                    lines.append(f"    - {p}")
            if self.returns:
                lines.append(f"  Returns: {self.returns}")
            if self.raises:
                lines.append("  Raises:")
                for r in self.raises:
                    lines.append(f"    - {r}")
            if self.side_effects:
                lines.append(f"  Side effects: {self.side_effects}")

        if self.type in (DocItemType.CLASS, DocItemType.DATATYPE):
            if self.attributes:
                lines.append("  Attributes:")
                for a in self.attributes:
                    lines.append(f"    - {a}")
            if self.dunder_methods:
                lines.append(f"  Dunder methods: {', '.join(self.dunder_methods)}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# File level
# ---------------------------------------------------------------------------


class FileDocType(Enum):
    CODE = "code"  # .py, .js, .ts, ... — contains DocItems
    CONFIG = "config"  # .yaml, .json, .toml, .ini, ...
    DOCS = "docs"  # .md, .rst, .txt, ...
    OTHER = "other"  # any other human-authored text file
    SKIPPED = "skipped"  # binary, generated, or lock files — not documented

    def __str__(self) -> str:
        return self.value


class FileDoc(BaseModel):
    """Documentation for a single file."""

    path: str
    type: FileDocType
    description: str  # empty string for SKIPPED
    items: list[DocItem] = []  # populated only for CODE files

    def __str__(self) -> str:
        lines = [f"file: {self.path} ({self.type})"]
        if self.description:
            lines.append(f"  {self.description}")
        if self.items:
            lines.append("  Entities:")
            for item in self.items:
                parent_part = f", parent: {item.parent}" if item.parent else ""
                lines.append(f"    - {item.name} ({item.type}{parent_part})")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Package level
# ---------------------------------------------------------------------------


class PackageDoc(BaseModel):
    """Documentation for a directory / package."""

    path: str
    description: str
    files: list[str] = []  # paths of direct FileDoc children
    packages: list[str] = []  # paths of direct PackageDoc children

    def __str__(self) -> str:
        lines = [f"package: {self.path}", f"  {self.description}"]
        if self.files:
            lines.append(f"  Files: {', '.join(self.files)}")
        if self.packages:
            lines.append(f"  Sub-packages: {', '.join(self.packages)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Project level
# ---------------------------------------------------------------------------


class ProjectDoc(BaseModel):
    """Top-level documentation for an entire project."""

    name: str
    description: str
    packages: list[str] = []  # paths of top-level PackageDoc children

    def __str__(self) -> str:
        lines = [f"project: {self.name}", f"  {self.description}"]
        if self.packages:
            lines.append(f"  Packages: {', '.join(self.packages)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
#  Config
# ---------------------------------------------------------------------------


class DocumentationCacheConfig(BaseModel):
    """Configuration for the documentation disk cache."""

    cache_dir: str
    use_cache: bool = True
    start_with_clean_cache: bool = False
    max_disk_size: int = 1_000_000_000  # bytes; evicts oldest entries first
    max_age: float = 86_400  # seconds; entries older than this are stale
    max_ram_size: Optional[int] = None  # max items in RAM cache; None = unlimited
