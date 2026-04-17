from __future__ import annotations

import pytest

from docai.errors import DocaiError
from docai.extractor.errors import ExtractionError


class TestExtractionErrorHappyPath:
    @pytest.mark.unit
    def test_instantiates_with_message_and_code(self) -> None:
        err = ExtractionError(message="something failed", code="EXTRACTION_LLM_FAILED")
        assert err.message == "something failed"
        assert err.code == "EXTRACTION_LLM_FAILED"

    @pytest.mark.unit
    def test_is_subclass_of_docai_error(self) -> None:
        err = ExtractionError(message="x", code="EXTRACTION_LLM_FAILED")
        assert isinstance(err, DocaiError)

    @pytest.mark.unit
    def test_can_be_caught_as_docai_error(self) -> None:
        with pytest.raises(DocaiError):
            raise ExtractionError(message="x", code="EXTRACTION_LLM_FAILED")

    @pytest.mark.unit
    def test_extraction_llm_failed_code(self) -> None:
        err = ExtractionError(message="LLM rate limited", code="EXTRACTION_LLM_FAILED")
        assert err.code == "EXTRACTION_LLM_FAILED"

    @pytest.mark.unit
    def test_extraction_read_failed_code(self) -> None:
        err = ExtractionError(message="cannot read file", code="EXTRACTION_READ_FAILED")
        assert err.code == "EXTRACTION_READ_FAILED"

    @pytest.mark.unit
    def test_preserves_cause_when_raised_with_from(self) -> None:
        cause = ValueError("original")
        try:
            raise ExtractionError(message="wrapped", code="EXTRACTION_READ_FAILED") from cause
        except ExtractionError as err:
            assert err.__cause__ is cause

    @pytest.mark.unit
    def test_format_compact_single_error(self) -> None:
        err = ExtractionError(message="LLM rate limited", code="EXTRACTION_LLM_FAILED")
        assert err.format_compact() == "[EXTRACTION_LLM_FAILED] LLM rate limited"

    @pytest.mark.unit
    def test_format_compact_chained_docai_errors(self) -> None:
        cause = ExtractionError(message="LLM rate limited", code="EXTRACTION_LLM_FAILED")
        err = ExtractionError(message="extraction failed", code="EXTRACTION_LLM_FAILED")
        err.__cause__ = cause
        assert err.format_compact() == (
            "[EXTRACTION_LLM_FAILED] extraction failed"
            " → [EXTRACTION_LLM_FAILED] LLM rate limited"
        )
