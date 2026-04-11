from __future__ import annotations

import pytest

from docai.discovery.datatypes import AssetSummary, DirectoryEntry


@pytest.fixture
def basic_entry() -> DirectoryEntry:
    return DirectoryEntry(
        child_packages=["src/core", "src/utils"],
        files=["src/main.py", "src/config.py"],
        assets=AssetSummary(count=2, types={"png": 1, "svg": 1}),
    )


class TestContentHashReturnType:
    @pytest.mark.unit
    def test_returns_str(self, basic_entry: DirectoryEntry) -> None:
        result = basic_entry.content_hash()
        assert isinstance(result, str)


class TestContentHashDeterminism:
    @pytest.mark.unit
    def test_same_model_returns_identical_hash(self, basic_entry: DirectoryEntry) -> None:
        assert basic_entry.content_hash() == basic_entry.content_hash()


class TestContentHashSensitivity:
    @pytest.mark.unit
    def test_different_files_produces_different_hash(self) -> None:
        a = DirectoryEntry(child_packages=[], files=["src/a.py"], assets=None)
        b = DirectoryEntry(child_packages=[], files=["src/b.py"], assets=None)
        assert a.content_hash() != b.content_hash()

    @pytest.mark.unit
    def test_different_child_packages_produces_different_hash(self) -> None:
        a = DirectoryEntry(child_packages=["src/core"], files=[], assets=None)
        b = DirectoryEntry(child_packages=["src/utils"], files=[], assets=None)
        assert a.content_hash() != b.content_hash()

    @pytest.mark.unit
    def test_different_assets_produces_different_hash(self) -> None:
        a = DirectoryEntry(child_packages=[], files=[], assets=AssetSummary(count=1, types={"png": 1}))
        b = DirectoryEntry(child_packages=[], files=[], assets=AssetSummary(count=2, types={"svg": 2}))
        assert a.content_hash() != b.content_hash()


class TestContentHashOrderIndependence:
    @pytest.mark.unit
    def test_files_in_different_order_produce_same_hash(self) -> None:
        a = DirectoryEntry(child_packages=[], files=["src/a.py", "src/b.py"], assets=None)
        b = DirectoryEntry(child_packages=[], files=["src/b.py", "src/a.py"], assets=None)
        assert a.content_hash() == b.content_hash()

    @pytest.mark.unit
    def test_child_packages_in_different_order_produce_same_hash(self) -> None:
        a = DirectoryEntry(child_packages=["src/core", "src/utils"], files=[], assets=None)
        b = DirectoryEntry(child_packages=["src/utils", "src/core"], files=[], assets=None)
        assert a.content_hash() == b.content_hash()


class TestContentHashEdgeCases:
    @pytest.mark.unit
    def test_assets_none_returns_valid_str(self) -> None:
        entry = DirectoryEntry(child_packages=["src/core"], files=["src/main.py"], assets=None)
        result = entry.content_hash()
        assert isinstance(result, str)

    @pytest.mark.unit
    def test_all_fields_empty_returns_valid_str(self) -> None:
        entry = DirectoryEntry(child_packages=[], files=[], assets=None)
        result = entry.content_hash()
        assert isinstance(result, str)
