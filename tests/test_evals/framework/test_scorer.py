from __future__ import annotations

import pytest

from docai.extractor.datatypes import Entity, EntityCategory, FileAnalysis, FileType
from tests.evals.framework.cases import CaseEntity, EvalCase
from tests.evals.framework.scorer import EvalResult, score


def _make_case(**kwargs) -> EvalCase:
    defaults = dict(
        id="source__python__simple",
        fixture="tests/fixtures/source/python/simple.py",
        language="python",
        file_type="source_file",
        expected_deps=[],
        must_contain=[],
        should_not_contain=[],
        tags=["python"],
        area="extractor",
    )
    defaults.update(kwargs)
    return EvalCase(**defaults)


def _make_entity(name: str, category: str, kind: str = "function") -> Entity:
    return Entity(
        category=EntityCategory(category),
        name=name,
        kind=kind,
        parent=None,
        signature=None,
    )


def _make_analysis(**kwargs) -> FileAnalysis:
    defaults = dict(
        file_path="tests/fixtures/source/python/simple.py",
        file_type=FileType.source_file,
        entities=[],
        dependencies=[],
    )
    defaults.update(kwargs)
    return FileAnalysis(**defaults)


class TestScoreFileType:
    @pytest.mark.unit
    def test_file_type_match_when_equal(self) -> None:
        case = _make_case(file_type="source_file")
        actual = _make_analysis(file_type=FileType.source_file)
        result = score(case, actual)
        assert result.file_type_match is True

    @pytest.mark.unit
    def test_file_type_no_match_when_different(self) -> None:
        case = _make_case(file_type="config_file")
        actual = _make_analysis(file_type=FileType.source_file)
        result = score(case, actual)
        assert result.file_type_match is False


class TestScoreDeps:
    @pytest.mark.unit
    def test_deps_match_when_equal(self) -> None:
        case = _make_case(expected_deps=["a.py", "b.py"])
        actual = _make_analysis(dependencies=["b.py", "a.py"])
        result = score(case, actual)
        assert result.deps_match is True

    @pytest.mark.unit
    def test_deps_no_match_when_different(self) -> None:
        case = _make_case(expected_deps=["a.py"])
        actual = _make_analysis(dependencies=["b.py"])
        result = score(case, actual)
        assert result.deps_match is False

    @pytest.mark.unit
    def test_deps_match_empty(self) -> None:
        case = _make_case(expected_deps=[])
        actual = _make_analysis(dependencies=[])
        result = score(case, actual)
        assert result.deps_match is True


class TestScoreEntities:
    @pytest.mark.unit
    def test_pct_entities_found_100_when_must_contain_empty(self) -> None:
        case = _make_case(must_contain=[])
        actual = _make_analysis()
        result = score(case, actual)
        assert result.pct_entities_found == 100.0

    @pytest.mark.unit
    def test_pct_entities_found_100_when_all_found(self) -> None:
        case = _make_case(must_contain=[
            CaseEntity(name="foo", category="callable"),
            CaseEntity(name="Bar", category="type"),
        ])
        actual = _make_analysis(entities=[
            _make_entity("foo", "callable"),
            _make_entity("Bar", "type", kind="class"),
        ])
        result = score(case, actual)
        assert result.pct_entities_found == 100.0

    @pytest.mark.unit
    def test_pct_entities_found_partial(self) -> None:
        case = _make_case(must_contain=[
            CaseEntity(name="foo", category="callable"),
            CaseEntity(name="bar", category="callable"),
            CaseEntity(name="baz", category="callable"),
            CaseEntity(name="qux", category="callable"),
        ])
        actual = _make_analysis(entities=[
            _make_entity("foo", "callable"),
            _make_entity("bar", "callable"),
        ])
        result = score(case, actual)
        assert result.pct_entities_found == 50.0

    @pytest.mark.unit
    def test_pct_entities_found_zero_when_none_found(self) -> None:
        case = _make_case(must_contain=[CaseEntity(name="foo", category="callable")])
        actual = _make_analysis(entities=[])
        result = score(case, actual)
        assert result.pct_entities_found == 0.0

    @pytest.mark.unit
    def test_false_entities_matched_against_should_not_contain(self) -> None:
        case = _make_case(should_not_contain=[
            CaseEntity(name="internal_helper", category="callable"),
        ])
        actual = _make_analysis(entities=[
            _make_entity("internal_helper", "callable"),
            _make_entity("public_api", "callable"),
        ])
        result = score(case, actual)
        assert len(result.false_entities) == 1
        assert result.false_entities[0].name == "internal_helper"

    @pytest.mark.unit
    def test_false_entities_empty_when_no_violations(self) -> None:
        case = _make_case(should_not_contain=[CaseEntity(name="bad", category="callable")])
        actual = _make_analysis(entities=[_make_entity("good", "callable")])
        result = score(case, actual)
        assert result.false_entities == []

    @pytest.mark.unit
    def test_extra_entities_are_neither_must_nor_should_not(self) -> None:
        case = _make_case(
            must_contain=[CaseEntity(name="foo", category="callable")],
            should_not_contain=[CaseEntity(name="bad", category="callable")],
        )
        actual = _make_analysis(entities=[
            _make_entity("foo", "callable"),
            _make_entity("extra", "callable"),
        ])
        result = score(case, actual)
        assert len(result.extra_entities) == 1
        assert result.extra_entities[0].name == "extra"

    @pytest.mark.unit
    def test_entity_match_uses_name_and_category_only(self) -> None:
        case = _make_case(must_contain=[CaseEntity(name="foo", category="callable")])
        actual = _make_analysis(entities=[
            Entity(
                category=EntityCategory.callable,
                name="foo",
                kind="method",
                parent="MyClass",
                signature="def foo(self):",
            )
        ])
        result = score(case, actual)
        assert result.pct_entities_found == 100.0

    @pytest.mark.unit
    def test_error_field_none_by_default(self) -> None:
        case = _make_case()
        actual = _make_analysis()
        result = score(case, actual)
        assert result.error is None

    @pytest.mark.unit
    def test_result_holds_case_reference(self) -> None:
        case = _make_case()
        actual = _make_analysis()
        result = score(case, actual)
        assert result.case is case
