from __future__ import annotations

import pytest

from docai.extractor.datatypes import Entity, EntityCategory, FileAnalysis, FileType


class TestFileTypeEnum:
    @pytest.mark.unit
    def test_has_exactly_four_members(self) -> None:
        assert len(FileType) == 4

    @pytest.mark.unit
    def test_values_are_correct_strings(self) -> None:
        assert FileType.source_file.value == "source_file"
        assert FileType.source_like_config.value == "source_like_config"
        assert FileType.config_file.value == "config_file"
        assert FileType.other.value == "other"


class TestEntityCategoryEnum:
    @pytest.mark.unit
    def test_has_exactly_five_members(self) -> None:
        assert len(EntityCategory) == 5

    @pytest.mark.unit
    def test_values_are_correct_strings(self) -> None:
        assert EntityCategory.callable.value == "callable"
        assert EntityCategory.macro.value == "macro"
        assert EntityCategory.type.value == "type"
        assert EntityCategory.variable.value == "value"
        assert EntityCategory.implementation.value == "implementation"


class TestEntityConstruction:
    @pytest.mark.unit
    def test_all_fields_set(self) -> None:
        entity = Entity(
            category=EntityCategory.callable,
            name="parse",
            kind="function",
            parent="Parser",
            signature="def parse(content: str) -> AST:",
        )
        assert entity.category == EntityCategory.callable
        assert entity.name == "parse"
        assert entity.kind == "function"
        assert entity.parent == "Parser"
        assert entity.signature == "def parse(content: str) -> AST:"

    @pytest.mark.unit
    def test_parent_none(self) -> None:
        entity = Entity(
            category=EntityCategory.type,
            name="Parser",
            kind="class",
            parent=None,
            signature="class Parser:",
        )
        assert entity.parent is None

    @pytest.mark.unit
    def test_signature_none(self) -> None:
        entity = Entity(
            category=EntityCategory.variable,
            name="MAX_RETRIES",
            kind="constant",
            parent=None,
            signature=None,
        )
        assert entity.signature is None

    @pytest.mark.unit
    def test_both_optional_fields_none(self) -> None:
        entity = Entity(
            category=EntityCategory.implementation,
            name="Display",
            kind="trait_impl",
            parent=None,
            signature=None,
        )
        assert entity.parent is None
        assert entity.signature is None


class TestEntitySerialization:
    @pytest.mark.unit
    def test_json_round_trip(self) -> None:
        entity = Entity(
            category=EntityCategory.callable,
            name="parse",
            kind="function",
            parent="Parser",
            signature="def parse(content: str) -> AST:",
        )
        restored = Entity.model_validate_json(entity.model_dump_json())
        assert restored.category == entity.category
        assert restored.name == entity.name
        assert restored.kind == entity.kind
        assert restored.parent == entity.parent
        assert restored.signature == entity.signature

    @pytest.mark.unit
    def test_json_round_trip_with_none_fields(self) -> None:
        entity = Entity(
            category=EntityCategory.macro,
            name="MAX",
            kind="macro",
            parent=None,
            signature=None,
        )
        restored = Entity.model_validate_json(entity.model_dump_json())
        assert restored.parent is None
        assert restored.signature is None


class TestFileAnalysisConstruction:
    @pytest.mark.unit
    def test_empty_entities_and_dependencies(self) -> None:
        analysis = FileAnalysis(
            file_path="src/docai/main.py",
            file_type=FileType.source_file,
            entities=[],
            dependencies=[],
        )
        assert analysis.file_path == "src/docai/main.py"
        assert analysis.file_type == FileType.source_file
        assert analysis.entities == []
        assert analysis.dependencies == []

    @pytest.mark.unit
    def test_populated_entities_and_dependencies(self) -> None:
        entity = Entity(
            category=EntityCategory.callable,
            name="run",
            kind="function",
            parent=None,
            signature="def run() -> None:",
        )
        analysis = FileAnalysis(
            file_path="src/docai/runner.py",
            file_type=FileType.source_file,
            entities=[entity],
            dependencies=["src/docai/main.py"],
        )
        assert analysis.file_path == "src/docai/runner.py"
        assert len(analysis.entities) == 1
        assert analysis.entities[0].name == "run"
        assert analysis.dependencies == ["src/docai/main.py"]


class TestFileAnalysisSerialization:
    @pytest.mark.unit
    def test_json_round_trip(self) -> None:
        entity = Entity(
            category=EntityCategory.type,
            name="Runner",
            kind="class",
            parent=None,
            signature="class Runner:",
        )
        analysis = FileAnalysis(
            file_path="src/docai/runner.py",
            file_type=FileType.source_file,
            entities=[entity],
            dependencies=["src/docai/main.py"],
        )
        restored = FileAnalysis.model_validate_json(analysis.model_dump_json())
        assert restored.file_path == analysis.file_path
        assert restored.file_type == analysis.file_type
        assert len(restored.entities) == 1
        assert restored.entities[0].name == "Runner"
        assert restored.dependencies == analysis.dependencies

    @pytest.mark.unit
    def test_json_round_trip_config_file(self) -> None:
        analysis = FileAnalysis(
            file_path="Dockerfile",
            file_type=FileType.config_file,
            entities=[],
            dependencies=[],
        )
        restored = FileAnalysis.model_validate_json(analysis.model_dump_json())
        assert restored.file_type == FileType.config_file
        assert restored.entities == []
