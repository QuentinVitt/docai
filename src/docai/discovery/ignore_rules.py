from __future__ import annotations

from logging import getLogger
from pathlib import Path

import pathspec

from docai.discovery.datatypes import FileOverride

logger = getLogger(__name__)


class IgnoreRules:
    def __init__(self, patterns: list[str]) -> None:
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        exclude_only = [p for p in patterns if not p.strip().startswith("!")]
        self._exclude_spec = pathspec.PathSpec.from_lines("gitignore", exclude_only)
        self._silenced_negations: set[str] = set()

    def file_override(self, path: Path) -> FileOverride | None:
        path_str = str(path)
        for parent in path.parents:
            if parent != Path(".") and self.should_prune_directory(parent):
                if (
                    not self._spec.match_file(path_str)
                    and self._exclude_spec.match_file(path_str)
                    and path_str not in self._silenced_negations
                ):
                    self._silenced_negations.add(path_str)
                    logger.warning(
                        "Negation pattern has no effect: parent directory '%s' is excluded. "
                        "'%s' will not be force-included.",
                        parent,
                        path_str,
                    )
                return None
        if self._spec.match_file(path_str):
            return FileOverride.exclude
        if self._exclude_spec.match_file(path_str):
            return FileOverride.include
        return None

    def should_prune_directory(self, path: Path) -> bool:
        path_str = str(path)
        matches_as_dir = self._spec.match_file(path_str + "/")
        matches_as_file = self._spec.match_file(path_str)
        return matches_as_dir and not matches_as_file
