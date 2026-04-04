import pytest

from docai.errors import DocaiError


@pytest.mark.unit
class TestDocaiErrorFields:
    def test_has_message_field(self) -> None:
        error = DocaiError(message="something went wrong", code="SOME_ERROR")
        assert error.message == "something went wrong"

    def test_has_code_field(self) -> None:
        error = DocaiError(message="something went wrong", code="SOME_ERROR")
        assert error.code == "SOME_ERROR"

    def test_message_and_code_set_correctly(self) -> None:
        error = DocaiError(message="rate limit exceeded", code="LLM_RATE_LIMIT")
        assert error.message == "rate limit exceeded"
        assert error.code == "LLM_RATE_LIMIT"

    def test_cause_chain_accessible(self) -> None:
        cause = DocaiError(message="root cause", code="ROOT_ERROR")
        error = DocaiError(message="top error", code="TOP_ERROR")
        error.__cause__ = cause
        assert error.__cause__ is cause
        assert error.__cause__.message == "root cause"


@pytest.mark.unit
class TestFormatCompact:
    def test_single_error_no_chain(self) -> None:
        error = DocaiError(
            message="API key not found. Set GEMINI_API_KEY or add api_key to docai.toml.",
            code="CONFIG_MISSING_API_KEY",
        )
        assert error.format_compact() == (
            "[CONFIG_MISSING_API_KEY] API key not found. Set GEMINI_API_KEY or add api_key to docai.toml."
        )

    def test_single_error_state_locked(self) -> None:
        error = DocaiError(
            message="another docai process is already running (PID 48291).",
            code="STATE_LOCKED",
        )
        assert error.format_compact() == (
            "[STATE_LOCKED] another docai process is already running (PID 48291)."
        )

    def test_single_error_no_files(self) -> None:
        error = DocaiError(
            message="no processable files found. Check your .docaiignore or run docai list.",
            code="PIPELINE_NO_FILES",
        )
        assert error.format_compact() == (
            "[PIPELINE_NO_FILES] no processable files found. Check your .docaiignore or run docai list."
        )

    def test_single_error_permission_denied(self) -> None:
        error = DocaiError(
            message="cannot read src/secret.py — permission denied",
            code="DISCOVERY_PERMISSION_DENIED",
        )
        assert error.format_compact() == (
            "[DISCOVERY_PERMISSION_DENIED] cannot read src/secret.py — permission denied"
        )

    def test_two_level_chain(self) -> None:
        root = DocaiError(
            message="LLM validation failed after 3 retries",
            code="LLM_VALIDATION_EXHAUSTED",
        )
        top = DocaiError(
            message="failed to extract src/parser.py",
            code="EXTRACTION_PARSE_FAILED",
        )
        top.__cause__ = root

        assert top.format_compact() == (
            "[EXTRACTION_PARSE_FAILED] failed to extract src/parser.py"
            " → [LLM_VALIDATION_EXHAUSTED] LLM validation failed after 3 retries"
        )

    def test_three_level_chain(self) -> None:
        root = DocaiError(
            message="rate limit exceeded after 3 retries",
            code="LLM_RATE_LIMIT",
        )
        mid = DocaiError(
            message="failed to document src/parser.py",
            code="GENERATION_FAILED",
        )
        top = DocaiError(
            message="pipeline aborted",
            code="PIPELINE_ABORTED",
        )
        mid.__cause__ = root
        top.__cause__ = mid

        assert top.format_compact() == (
            "[PIPELINE_ABORTED] pipeline aborted"
            " → [GENERATION_FAILED] failed to document src/parser.py"
            " → [LLM_RATE_LIMIT] rate limit exceeded after 3 retries"
        )

    def test_chain_stops_at_non_docai_error(self) -> None:
        raw = PermissionError("permission denied")
        top = DocaiError(
            message="cannot read src/secret.py — permission denied",
            code="DISCOVERY_PERMISSION_DENIED",
        )
        top.__cause__ = raw

        assert top.format_compact() == (
            "[DISCOVERY_PERMISSION_DENIED] cannot read src/secret.py — permission denied"
        )
