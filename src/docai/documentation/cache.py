import hashlib
import json
import logging
import os
import shutil
import time
from collections import OrderedDict
from typing import Optional

from docai.config.datatypes import DocumentationCacheConfig
from docai.documentation.datatypes import (
    DocItem,
    DocItemRef,
    DocItemType,
    EntityQuery,
    FileDoc,
    PackageDoc,
    ProjectDoc,
)

logger = logging.getLogger(__name__)


def _make_hash(*parts: str) -> str:
    raw = ":".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class DocumentationCache:
    def __init__(self, config: DocumentationCacheConfig, project_path: str):
        self._ram: OrderedDict[str, object] = OrderedDict()
        self._max_ram_size: Optional[int] = config.max_ram_size
        self.cache_dir = os.path.abspath(os.path.join(project_path, config.cache_dir))
        self.max_age = config.max_age
        self.max_disk_size = config.max_disk_size

        if self.max_age < 0:
            raise ValueError(f"max_age cannot be negative: {self.max_age}")
        if self.max_disk_size < 0:
            raise ValueError(f"max_disk_size cannot be negative: {self.max_disk_size}")

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        elif not os.path.isdir(self.cache_dir):
            raise ValueError(f"Cache path is not a directory: {self.cache_dir}")

        if not os.access(self.cache_dir, os.W_OK | os.R_OK):
            raise ValueError(
                f"Cache directory is not readable/writable: {self.cache_dir}"
            )

        if config.start_with_clean_cache:
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir)
        else:
            self._evict_stale()
            self._evict_to_size()

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, key + ".json")

    def _scan_cache_dir(self) -> tuple[list[tuple[float, str, int]], int]:
        files: list[tuple[float, str, int]] = []
        total_size = 0
        for root, _, filenames in os.walk(self.cache_dir):
            for filename in filenames:
                filepath = os.path.join(root, filename)
                try:
                    mtime = os.path.getmtime(filepath)
                    size = os.path.getsize(filepath)
                    files.append((mtime, filepath, size))
                    total_size += size
                except OSError:
                    pass
        return files, total_size

    def _delete_file(self, filepath: str) -> None:
        try:
            os.remove(filepath)
        except OSError as e:
            logger.warning("Failed to delete cache file %s: %s", filepath, e)

    def _get_source_mtime(self, source_path: str, level: str) -> float:
        """Returns the newest mtime of the documented source (file or directory)."""
        if level in ("entity", "file"):
            try:
                return os.path.getmtime(source_path)
            except OSError:
                return float("inf")
        else:  # package or project — newest mtime across all files in the tree
            newest = 0.0
            try:
                for root, _, files in os.walk(source_path):
                    for f in files:
                        try:
                            mtime = os.path.getmtime(os.path.join(root, f))
                            if mtime > newest:
                                newest = mtime
                        except OSError:
                            pass
            except OSError:
                return float("inf")
            return newest

    def _evict_stale(self) -> None:
        cutoff = time.time() - self.max_age
        cached_files, _ = self._scan_cache_dir()
        for cache_mtime, filepath, _ in cached_files:
            if cache_mtime < cutoff:
                self._delete_file(filepath)
                continue
            try:
                with open(filepath) as f:
                    content = json.load(f)
                source_mtime = self._get_source_mtime(
                    content.get("source_path", ""), content.get("level", "file")
                )
                if source_mtime > cache_mtime:
                    self._delete_file(filepath)
            except (OSError, json.JSONDecodeError):
                self._delete_file(filepath)

    def _evict_to_size(self) -> None:
        cached_files, cache_size = self._scan_cache_dir()
        if cache_size <= self.max_disk_size:
            return
        cached_files.sort(key=lambda x: x[0])  # oldest first
        while cache_size > self.max_disk_size and cached_files:
            _, filepath, size = cached_files.pop(0)
            self._delete_file(filepath)
            cache_size -= size

    def _ram_get(self, key: str) -> object | None:
        if key not in self._ram:
            return None
        self._ram.move_to_end(key)
        return self._ram[key]

    def _ram_put(self, key: str, value: object) -> None:
        if key in self._ram:
            self._ram.move_to_end(key)
            self._ram[key] = value
            return
        if self._max_ram_size is not None and len(self._ram) >= self._max_ram_size:
            self._ram.popitem(last=False)  # evict least-recently-used
        self._ram[key] = value

    def _disk_write(self, key: str, level: str, source_path: str, doc: dict) -> None:
        path = self._cache_path(key)
        try:
            with open(path, "w") as f:
                json.dump({"level": level, "source_path": source_path, "doc": doc}, f)
        except OSError as e:
            logger.warning("Failed to write cache file %s: %s", path, e)

    def _disk_read(self, key: str) -> dict | None:
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            cache_mtime = os.path.getmtime(path)
            if cache_mtime < time.time() - self.max_age:
                self._delete_file(path)
                return None
            with open(path) as f:
                content = json.load(f)
            source_mtime = self._get_source_mtime(
                content.get("source_path", ""), content.get("level", "file")
            )
            if source_mtime > cache_mtime:
                self._delete_file(path)
                return None
            return content
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read cache file %s: %s", path, e)
            return None

    # ---------------------------------------------------------------------------
    # Project
    # ---------------------------------------------------------------------------

    def _project_key(self, project_name: str | None) -> str:
        return _make_hash("project", project_name or "")

    def get_project_documentation(self, project_name: str | None) -> ProjectDoc | None:
        key = self._project_key(project_name)
        cached = self._ram_get(key)
        if cached is not None:
            return cached  # type: ignore
        content = self._disk_read(key)
        if content is None:
            return None
        doc = ProjectDoc.model_validate(content["doc"])
        self._ram_put(key, doc)
        return doc

    def set_project_documentation(
        self, project_name: str | None, source_path: str, doc: ProjectDoc
    ) -> None:
        key = self._project_key(project_name)
        self._disk_write(key, "project", source_path, doc.model_dump(mode="json"))
        self._ram_put(key, doc)

    # ---------------------------------------------------------------------------
    # Package
    # ---------------------------------------------------------------------------

    def _package_key(self, package_path: str) -> str:
        return _make_hash("package", package_path)

    def get_package_documentation(self, package_path: str) -> PackageDoc | None:
        key = self._package_key(package_path)
        cached = self._ram_get(key)
        if cached is not None:
            return cached  # type: ignore
        content = self._disk_read(key)
        if content is None:
            return None
        doc = PackageDoc.model_validate(content["doc"])
        self._ram_put(key, doc)
        return doc

    def set_package_documentation(self, package_path: str, doc: PackageDoc) -> None:
        key = self._package_key(package_path)
        self._disk_write(key, "package", package_path, doc.model_dump(mode="json"))
        self._ram_put(key, doc)

    # ---------------------------------------------------------------------------
    # File
    # ---------------------------------------------------------------------------

    def _file_key(self, file_path: str) -> str:
        return _make_hash("file", file_path)

    def get_file_documentation(self, file_path: str) -> FileDoc | None:
        key = self._file_key(file_path)
        cached = self._ram_get(key)
        if cached is not None:
            return cached  # type: ignore
        content = self._disk_read(key)
        if content is None:
            return None
        doc = FileDoc.model_validate(content["doc"])
        self._ram_put(key, doc)
        return doc

    def set_file_documentation(self, file_path: str, doc: FileDoc) -> None:
        key = self._file_key(file_path)
        self._disk_write(key, "file", file_path, doc.model_dump(mode="json"))
        self._ram_put(key, doc)

    # ---------------------------------------------------------------------------
    # Entity
    # ---------------------------------------------------------------------------

    def _entity_key(self, file_path: str, ref: DocItemRef) -> str:
        return _make_hash(
            "entity", file_path, ref.type.value, ref.parent or "", ref.name
        )

    def get_entity_documentation(
        self, file_path: str, ref: DocItemRef
    ) -> DocItem | None:
        key = self._entity_key(file_path, ref)
        cached = self._ram_get(key)
        if cached is not None:
            return cached  # type: ignore
        content = self._disk_read(key)
        if content is None:
            return None
        doc = DocItem.model_validate(content["doc"])
        self._ram_put(key, doc)
        return doc

    def set_entity_documentation(
        self, file_path: str, ref: DocItemRef, doc: DocItem
    ) -> None:
        key = self._entity_key(file_path, ref)
        self._disk_write(key, "entity", file_path, doc.model_dump(mode="json"))
        self._ram_put(key, doc)

    # ---------------------------------------------------------------------------
    # Search / fuzzy lookup
    # ---------------------------------------------------------------------------

    def _fuzzy_match_refs(
        self,
        refs: list[DocItemRef],
        entity_name: str,
        entity_type: DocItemType | None = None,
        parent: str | None = None,
    ) -> list[DocItemRef]:
        """Return the highest-priority tier of refs matching entity_name.

        Per name-match level (exact → case-insensitive → substring), priority is:
          type + parent > parent only > type only > neither
        None values for entity_type / parent mean "no constraint".
        """
        name_lower = entity_name.lower()

        def _type_ok(ref: DocItemRef) -> bool:
            return entity_type is None or ref.type == entity_type

        def _parent_ok(ref: DocItemRef) -> bool:
            return parent is None or ref.parent == parent

        def _tiers():
            yield [r for r in refs if r.name == entity_name and _type_ok(r) and _parent_ok(r)]
            yield [r for r in refs if r.name == entity_name and _parent_ok(r)]
            yield [r for r in refs if r.name == entity_name and _type_ok(r)]
            yield [r for r in refs if r.name == entity_name]
            yield [r for r in refs if r.name.lower() == name_lower and _type_ok(r) and _parent_ok(r)]
            yield [r for r in refs if r.name.lower() == name_lower and _parent_ok(r)]
            yield [r for r in refs if r.name.lower() == name_lower and _type_ok(r)]
            yield [r for r in refs if r.name.lower() == name_lower]
            yield [r for r in refs if name_lower in r.name.lower() and _type_ok(r) and _parent_ok(r)]
            yield [r for r in refs if name_lower in r.name.lower() and _parent_ok(r)]
            yield [r for r in refs if name_lower in r.name.lower() and _type_ok(r)]
            yield [r for r in refs if name_lower in r.name.lower()]

        for tier in _tiers():
            if tier:
                return tier
        return []

    def search_documentation(
        self,
        file_path: str,
        queries: list[EntityQuery] | None = None,
    ) -> tuple[FileDoc | None, list[DocItem]]:
        """Return (file_doc, matched_items) with full DocItem objects.

        queries=None: loads and returns all DocItems for the file.
        queries=[...]: runs each query and returns the union, deduplicated by
                       (name, type, parent).

        Per query:
          - name=None: filter refs by type/parent directly (no fuzzy matching).
          - name given: fuzzy-match against refs using type and parent as hints.
        """
        file_doc = self.get_file_documentation(file_path)
        if file_doc is None:
            return None, []

        refs = file_doc.items

        if queries is None:
            docs: list[DocItem] = []
            for ref in refs:
                doc = self.get_entity_documentation(file_path, ref)
                if doc is not None:
                    docs.append(doc)
            return file_doc, docs

        seen: set[tuple[str, str, str | None]] = set()
        docs = []
        for query in queries:
            if query.name is None:
                matched = [
                    r for r in refs
                    if (query.type is None or r.type == query.type)
                    and (query.parent is None or r.parent == query.parent)
                ]
            else:
                matched = self._fuzzy_match_refs(refs, query.name, query.type, query.parent)
            for ref in matched:
                identity = (ref.name, ref.type.value, ref.parent)
                if identity in seen:
                    continue
                seen.add(identity)
                doc = self.get_entity_documentation(file_path, ref)
                if doc is not None:
                    docs.append(doc)
        return file_doc, docs
