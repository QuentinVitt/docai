from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.evals.framework.cases import CaseEntity, EvalCase, load_cases


@pytest.fixture
def cases_root(tmp_path: Path) -> Path:
    return tmp_path


def _write_case(root: Path, rel_path: str, data: dict) -> None:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(data))


class TestLoadCasesHappyPath:
    @pytest.mark.unit
    def test_returns_empty_when_area_dir_missing(self, cases_root: Path) -> None:
        result = load_cases("extractor", cases_root=cases_root)
        assert result == []

    @pytest.mark.unit
    def test_returns_single_case(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/exceptions.yaml", {
            "fixture": "tests/fixtures/source/python/exceptions.py",
            "language": "python",
            "file_type": "source_file",
            "expected_deps": [],
            "must_contain": [{"name": "RequestException", "category": "type"}],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert len(result) == 1
        case = result[0]
        assert case.id == "source__python__exceptions"
        assert case.fixture == "tests/fixtures/source/python/exceptions.py"
        assert case.language == "python"
        assert case.file_type == "source_file"
        assert case.expected_deps == []
        assert case.must_contain == [CaseEntity(name="RequestException", category="type")]
        assert case.area == "extractor"

    @pytest.mark.unit
    def test_defaults_should_not_contain_and_tags_when_absent(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/simple.yaml", {
            "fixture": "tests/fixtures/source/python/simple.py",
            "language": "python",
            "file_type": "source_file",
            "expected_deps": [],
            "must_contain": [],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result[0].should_not_contain == []
        assert result[0].tags == []

    @pytest.mark.unit
    def test_parses_should_not_contain(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/simple.yaml", {
            "fixture": "tests/fixtures/source/python/simple.py",
            "language": "python",
            "file_type": "source_file",
            "expected_deps": [],
            "must_contain": [],
            "should_not_contain": [{"name": "helper", "category": "callable"}],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result[0].should_not_contain == [CaseEntity(name="helper", category="callable")]

    @pytest.mark.unit
    def test_parses_tags(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/simple.yaml", {
            "fixture": "tests/fixtures/source/python/simple.py",
            "language": "python",
            "file_type": "source_file",
            "expected_deps": [],
            "must_contain": [],
            "tags": ["python", "large"],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result[0].tags == ["python", "large"]

    @pytest.mark.unit
    def test_sorts_results_by_id(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/z_last.yaml", {
            "fixture": "tests/fixtures/source/python/z_last.py",
            "language": "python", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        _write_case(cases_root, "extractor/source/python/a_first.yaml", {
            "fixture": "tests/fixtures/source/python/a_first.py",
            "language": "python", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result[0].id == "source__python__a_first"
        assert result[1].id == "source__python__z_last"

    @pytest.mark.unit
    def test_id_replaces_slashes_with_double_underscore(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/go/scanner.yaml", {
            "fixture": "tests/fixtures/source/go/scanner.go",
            "language": "go", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result[0].id == "source__go__scanner"

    @pytest.mark.unit
    def test_id_replaces_dots_with_underscore(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/typescript/basic.d.ts.yaml", {
            "fixture": "tests/fixtures/source/typescript/basic.d.ts",
            "language": "typescript", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result[0].id == "source__typescript__basic_d_ts"

    @pytest.mark.unit
    def test_scans_subdirectories_recursively(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/a.yaml", {
            "fixture": "tests/fixtures/source/python/a.py",
            "language": "python", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        _write_case(cases_root, "extractor/source/go/b.yaml", {
            "fixture": "tests/fixtures/source/go/b.go",
            "language": "go", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        result = load_cases("extractor", cases_root=cases_root)
        ids = [c.id for c in result]
        assert "source__python__a" in ids
        assert "source__go__b" in ids


class TestLoadCasesFiltering:
    @pytest.mark.unit
    def test_filters_by_ids(self, cases_root: Path) -> None:
        for name in ["a", "b", "c"]:
            _write_case(cases_root, f"extractor/source/python/{name}.yaml", {
                "fixture": f"tests/fixtures/source/python/{name}.py",
                "language": "python", "file_type": "source_file",
                "expected_deps": [], "must_contain": [],
            })
        result = load_cases("extractor", ids=["source__python__a", "source__python__c"], cases_root=cases_root)
        assert [c.id for c in result] == ["source__python__a", "source__python__c"]

    @pytest.mark.unit
    def test_returns_all_when_ids_is_none(self, cases_root: Path) -> None:
        for name in ["a", "b"]:
            _write_case(cases_root, f"extractor/source/python/{name}.yaml", {
                "fixture": f"tests/fixtures/source/python/{name}.py",
                "language": "python", "file_type": "source_file",
                "expected_deps": [], "must_contain": [],
            })
        result = load_cases("extractor", ids=None, cases_root=cases_root)
        assert len(result) == 2


class TestLoadCasesErrorHandling:
    @pytest.mark.unit
    def test_skips_malformed_yaml(self, cases_root: Path) -> None:
        p = cases_root / "extractor" / "source" / "python" / "bad.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ invalid yaml: [")
        _write_case(cases_root, "extractor/source/python/good.yaml", {
            "fixture": "tests/fixtures/source/python/good.py",
            "language": "python", "file_type": "source_file",
            "expected_deps": [], "must_contain": [],
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert len(result) == 1
        assert result[0].id == "source__python__good"

    @pytest.mark.unit
    def test_skips_missing_required_fields(self, cases_root: Path) -> None:
        _write_case(cases_root, "extractor/source/python/incomplete.yaml", {
            "language": "python",
            # missing fixture, file_type, etc.
        })
        result = load_cases("extractor", cases_root=cases_root)
        assert result == []
