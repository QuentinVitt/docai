from __future__ import annotations

import json
from pathlib import Path

import pytest

from docai.extractor.datatypes import Entity, EntityCategory, FileAnalysis, FileType
from tests.evals.framework.cases import CaseEntity, EvalCase
from tests.evals.framework.reporter import print_results, save_results
from tests.evals.framework.scorer import EvalResult


def _make_case(id: str = "source__python__simple", **kwargs) -> EvalCase:
    defaults = dict(
        id=id,
        fixture=f"tests/fixtures/source/python/simple.py",
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


def _make_result(
    case: EvalCase | None = None,
    *,
    file_type_match: bool = True,
    deps_match: bool = True,
    pct_entities_found: float = 100.0,
    false_entities: list | None = None,
    extra_entities: list | None = None,
    error: str | None = None,
) -> EvalResult:
    return EvalResult(
        case=case or _make_case(),
        file_type_match=file_type_match,
        deps_match=deps_match,
        pct_entities_found=pct_entities_found,
        false_entities=false_entities or [],
        extra_entities=extra_entities or [],
        error=error,
    )


class TestPrintResults:
    @pytest.mark.unit
    def test_prints_without_error(self, capsys) -> None:
        results = [_make_result()]
        print_results(results)
        out = capsys.readouterr().out
        assert out.strip() != ""

    @pytest.mark.unit
    def test_prints_case_id_in_output(self, capsys) -> None:
        case = _make_case(id="source__python__exceptions")
        result = _make_result(case=case)
        print_results([result])
        out = capsys.readouterr().out
        assert "exceptions" in out

    @pytest.mark.unit
    def test_prints_pct_entities_found(self, capsys) -> None:
        result = _make_result(pct_entities_found=75.0)
        print_results([result])
        out = capsys.readouterr().out
        assert "75" in out

    @pytest.mark.unit
    def test_prints_summary_line(self, capsys) -> None:
        results = [
            _make_result(pct_entities_found=100.0),
            _make_result(pct_entities_found=50.0),
        ]
        print_results(results)
        out = capsys.readouterr().out
        assert "avg" in out.lower() or "%" in out

    @pytest.mark.unit
    def test_handles_empty_results(self, capsys) -> None:
        print_results([])
        out = capsys.readouterr().out
        assert "0" in out

    @pytest.mark.unit
    def test_prints_error_info_when_present(self, capsys) -> None:
        result = _make_result(error="[EXTRACTION_LLM_FAILED] LLM failed")
        print_results([result])
        out = capsys.readouterr().out
        assert "EXTRACTION_LLM_FAILED" in out or "error" in out.lower()


class TestSaveResults:
    @pytest.mark.integration
    def test_creates_summary_json(self, tmp_path: Path) -> None:
        result = _make_result()
        save_results([result], run_dir=tmp_path)
        assert (tmp_path / "summary.json").exists()

    @pytest.mark.integration
    def test_summary_json_is_valid(self, tmp_path: Path) -> None:
        result = _make_result()
        save_results([result], run_dir=tmp_path)
        data = json.loads((tmp_path / "summary.json").read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    @pytest.mark.integration
    def test_summary_includes_case_id(self, tmp_path: Path) -> None:
        case = _make_case(id="source__python__exceptions")
        result = _make_result(case=case)
        save_results([result], run_dir=tmp_path)
        data = json.loads((tmp_path / "summary.json").read_text())
        assert data[0]["case_id"] == "source__python__exceptions"

    @pytest.mark.integration
    def test_summary_includes_scores(self, tmp_path: Path) -> None:
        result = _make_result(pct_entities_found=80.0, file_type_match=True, deps_match=False)
        save_results([result], run_dir=tmp_path)
        data = json.loads((tmp_path / "summary.json").read_text())
        entry = data[0]
        assert entry["pct_entities_found"] == 80.0
        assert entry["file_type_match"] is True
        assert entry["deps_match"] is False

    @pytest.mark.integration
    def test_summary_includes_error_when_set(self, tmp_path: Path) -> None:
        result = _make_result(error="[EXTRACTION_LLM_FAILED] failed")
        save_results([result], run_dir=tmp_path)
        data = json.loads((tmp_path / "summary.json").read_text())
        assert data[0]["error"] == "[EXTRACTION_LLM_FAILED] failed"

    @pytest.mark.integration
    def test_creates_run_dir_if_missing(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "nested" / "run"
        save_results([], run_dir=run_dir)
        assert (run_dir / "summary.json").exists()
