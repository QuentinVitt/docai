from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docai.extractor.datatypes import FileAnalysis, FileType
from docai.extractor.errors import ExtractionError
from docai.llm.errors import LLMError
from tests.evals.framework.cases import CaseEntity, EvalCase
from tests.evals.framework.runner import run


def _make_case(fixture: str, language: str = "python", **kwargs) -> EvalCase:
    defaults = dict(
        id="source__python__simple",
        fixture=fixture,
        language=language,
        file_type="source_file",
        expected_deps=[],
        must_contain=[],
        should_not_contain=[],
        tags=[language],
        area="extractor",
    )
    defaults.update(kwargs)
    return EvalCase(**defaults)


def _make_analysis(file_path: str, file_type: FileType = FileType.source_file) -> FileAnalysis:
    return FileAnalysis(
        file_path=file_path,
        file_type=file_type,
        entities=[],
        dependencies=[],
    )


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    f = tmp_path / "tests" / "fixtures" / "source" / "python" / "simple.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("def foo(): pass\n")
    return tmp_path


class TestRunHappyPath:
    @pytest.mark.llm
    async def test_returns_eval_result_per_case(self, fixture_dir: Path) -> None:
        case = _make_case(
            fixture="tests/fixtures/source/python/simple.py",
            id="source__python__simple",
        )
        analysis = _make_analysis("tests/fixtures/source/python/simple.py")

        with patch("tests.evals.framework.runner.extract_with_llm", new=AsyncMock(return_value=analysis)), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            result = await run([case], llm_service=None)  # type: ignore[arg-type]

        assert len(result) == 1
        assert result[0].case is case
        assert result[0].error is None

    @pytest.mark.llm
    async def test_preserves_case_order_in_results(self, fixture_dir: Path) -> None:
        cases = []
        for name in ["a", "b", "c"]:
            f = fixture_dir / "tests" / "fixtures" / "source" / "python" / f"{name}.py"
            f.write_text(f"def {name}(): pass\n")
            cases.append(_make_case(
                fixture=f"tests/fixtures/source/python/{name}.py",
                id=f"source__python__{name}",
            ))

        analysis = _make_analysis("tests/fixtures/source/python/a.py")
        with patch("tests.evals.framework.runner.extract_with_llm", new=AsyncMock(return_value=analysis)), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            results = await run(cases, llm_service=None)  # type: ignore[arg-type]

        assert [r.case.id for r in results] == ["source__python__a", "source__python__b", "source__python__c"]

    @pytest.mark.llm
    async def test_returns_empty_list_for_empty_cases(self, fixture_dir: Path) -> None:
        with patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            result = await run([], llm_service=None)  # type: ignore[arg-type]
        assert result == []


class TestRunErrorHandling:
    @pytest.mark.llm
    async def test_extraction_error_sets_error_field(self, fixture_dir: Path) -> None:
        case = _make_case(fixture="tests/fixtures/source/python/simple.py")
        exc = ExtractionError(code="EXTRACTION_LLM_FAILED", message="LLM failed")

        with patch("tests.evals.framework.runner.extract_with_llm", new=AsyncMock(side_effect=exc)), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            results = await run([case], llm_service=None)  # type: ignore[arg-type]

        assert results[0].error is not None
        assert "EXTRACTION_LLM_FAILED" in results[0].error

    @pytest.mark.llm
    async def test_llm_error_sets_error_field(self, fixture_dir: Path) -> None:
        case = _make_case(fixture="tests/fixtures/source/python/simple.py")
        exc = LLMError(code="LLM_RATE_LIMIT", message="rate limited")

        with patch("tests.evals.framework.runner.extract_with_llm", new=AsyncMock(side_effect=exc)), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            results = await run([case], llm_service=None)  # type: ignore[arg-type]

        assert results[0].error is not None

    @pytest.mark.llm
    async def test_error_result_has_zero_pct_entities(self, fixture_dir: Path) -> None:
        case = _make_case(
            fixture="tests/fixtures/source/python/simple.py",
            must_contain=[CaseEntity(name="foo", category="callable")],
        )
        exc = ExtractionError(code="EXTRACTION_LLM_FAILED", message="failed")

        with patch("tests.evals.framework.runner.extract_with_llm", new=AsyncMock(side_effect=exc)), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            results = await run([case], llm_service=None)  # type: ignore[arg-type]

        assert results[0].pct_entities_found == 0.0
        assert results[0].file_type_match is False
        assert results[0].deps_match is False

    @pytest.mark.llm
    async def test_one_failure_does_not_abort_others(self, fixture_dir: Path) -> None:
        ok_file = fixture_dir / "tests" / "fixtures" / "source" / "python" / "ok.py"
        ok_file.write_text("def ok(): pass\n")

        case_fail = _make_case(
            fixture="tests/fixtures/source/python/simple.py",
            id="source__python__simple",
        )
        case_ok = _make_case(
            fixture="tests/fixtures/source/python/ok.py",
            id="source__python__ok",
        )
        ok_analysis = _make_analysis("tests/fixtures/source/python/ok.py")

        def side_effect(file_path, *args, **kwargs):
            if "simple" in file_path:
                raise ExtractionError(code="EXTRACTION_LLM_FAILED", message="fail")
            return ok_analysis

        with patch("tests.evals.framework.runner.extract_with_llm", new=AsyncMock(side_effect=side_effect)), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            results = await run([case_fail, case_ok], llm_service=None)  # type: ignore[arg-type]

        assert len(results) == 2
        fail_result = next(r for r in results if r.case.id == "source__python__simple")
        ok_result = next(r for r in results if r.case.id == "source__python__ok")
        assert fail_result.error is not None
        assert ok_result.error is None


class TestRunManifest:
    @pytest.mark.llm
    async def test_manifest_includes_fixture_files(self, fixture_dir: Path) -> None:
        case = _make_case(fixture="tests/fixtures/source/python/simple.py")
        analysis = _make_analysis("tests/fixtures/source/python/simple.py")
        captured_manifest = {}

        async def capture_extract(file_path, content, manifest_entry, file_manifest, llm_service):
            captured_manifest.update(file_manifest)
            return analysis

        with patch("tests.evals.framework.runner.extract_with_llm", new=capture_extract), \
             patch("tests.evals.framework.runner.PROJECT_ROOT", fixture_dir):
            await run([case], llm_service=None)  # type: ignore[arg-type]

        assert "tests/fixtures/source/python/simple.py" in captured_manifest
