from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from docai.llm.datatypes import LLMProfile, LogConfig, ModelConfig
from docai.llm.errors import LLMError
from docai.llm.service import LLMService

# All params a well-supported model exposes
ALL_SUPPORTED_PARAMS = [
    "temperature",
    "top_p",
    "n",
    "max_completion_tokens",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
    "response_format",
    "tools",
    "api_key",
    "base_url",
    "num_retries",
    "timeout",
]


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def log_config(log_dir: Path) -> LogConfig:
    return LogConfig(log_dir=log_dir)


@pytest.fixture
def minimal_profile() -> LLMProfile:
    return LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")])


@pytest.fixture
def litellm_ok():
    """Patch litellm so all params are supported (no api_key on minimal_profile, so check_valid_key is never called)."""
    with patch("litellm.get_supported_openai_params") as mock_params:
        mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
        yield mock_params


# ── construction ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestConstruction:
    def test_creates_with_valid_inputs(
        self, litellm_ok, minimal_profile: LLMProfile, log_config: LogConfig
    ) -> None:
        service = LLMService(profile=minimal_profile, log_config=log_config)
        assert service is not None

    def test_one_connection_per_model(
        self, litellm_ok, log_config: LogConfig
    ) -> None:
        profile = LLMProfile(
            models=[
                ModelConfig(model="gemini/gemini-2.0-flash"),
                ModelConfig(model="gemini/gemini-2.0-pro"),
            ]
        )
        service = LLMService(profile=profile, log_config=log_config)
        assert len(service._connections) == 2

    def test_global_semaphore_uses_profile_max_concurrency(
        self, litellm_ok, log_config: LogConfig
    ) -> None:
        profile = LLMProfile(
            models=[ModelConfig(model="gemini/gemini-2.0-flash")],
            max_concurrency=7,
        )
        service = LLMService(profile=profile, log_config=log_config)
        assert service._global_semaphore._value == 7

    def test_per_model_semaphore_uses_model_concurrency_when_below_profile_limit(
        self, litellm_ok, log_config: LogConfig
    ) -> None:
        profile = LLMProfile(
            models=[ModelConfig(model="gemini/gemini-2.0-flash", max_concurrency=3)],
            max_concurrency=10,
        )
        service = LLMService(profile=profile, log_config=log_config)
        _, _, semaphore = service._connections[0]
        assert semaphore._value == 3

    def test_per_model_semaphore_capped_at_profile_max_concurrency(
        self, litellm_ok, log_config: LogConfig
    ) -> None:
        profile = LLMProfile(
            models=[ModelConfig(model="gemini/gemini-2.0-flash", max_concurrency=20)],
            max_concurrency=5,
        )
        service = LLMService(profile=profile, log_config=log_config)
        _, _, semaphore = service._connections[0]
        assert semaphore._value == 5

    def test_capping_logs_debug_message(
        self,
        litellm_ok,
        log_config: LogConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        profile = LLMProfile(
            models=[ModelConfig(model="gemini/gemini-2.0-flash", max_concurrency=20)],
            max_concurrency=5,
        )
        with caplog.at_level(logging.DEBUG, logger="docai.llm.service"):
            LLMService(profile=profile, log_config=log_config)
        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert debug_messages == [
            "Model 'gemini/gemini-2.0-flash': max_concurrency 20 exceeds profile limit 5, capping to 5"
        ]


# ── API key validation ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestApiKeyValidation:
    def test_check_valid_key_failure_raises_llm_error(self, log_config: LogConfig) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.return_value = False
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(
                        models=[ModelConfig(model="gemini/gemini-2.0-flash", api_key="bad-key")]
                    ),
                    log_config=log_config,
                )
        assert exc_info.value.code == "LLM_AUTH_FAILED"

    def test_auth_failure_message_includes_model_name(self, log_config: LogConfig) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.return_value = False
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(
                        models=[ModelConfig(model="gemini/gemini-2.0-flash", api_key="bad-key")]
                    ),
                    log_config=log_config,
                )
        assert exc_info.value.message == "API key validation failed for model 'gemini/gemini-2.0-flash'"

    def test_check_valid_key_called_for_each_model_with_api_key(
        self, log_config: LogConfig
    ) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            LLMService(
                profile=LLMProfile(
                    models=[
                        ModelConfig(model="gemini/gemini-2.0-flash", api_key="key-a"),
                        ModelConfig(model="gemini/gemini-2.0-pro", api_key="key-b"),
                    ]
                ),
                log_config=log_config,
            )
        assert mock_key.call_count == 2

    def test_check_valid_key_skipped_when_no_api_key_in_config(
        self, log_config: LogConfig
    ) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            LLMService(
                profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
                log_config=log_config,
            )
        mock_key.assert_not_called()

    def test_check_valid_key_skipped_when_base_url_set(self, log_config: LogConfig) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            LLMService(
                profile=LLMProfile(
                    models=[
                        ModelConfig(
                            model="gemini/gemini-2.0-flash",
                            api_key="test-key",
                            base_url="https://custom.endpoint/",
                        )
                    ]
                ),
                log_config=log_config,
            )
        mock_key.assert_not_called()

    def test_check_valid_key_skipped_when_skip_api_key_validation_true(
        self, log_config: LogConfig
    ) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            LLMService(
                profile=LLMProfile(
                    models=[ModelConfig(model="gemini/gemini-2.0-flash", api_key="test-key")],
                    skip_api_key_validation=True,
                ),
                log_config=log_config,
            )
        mock_key.assert_not_called()

    def test_exception_from_check_valid_key_wrapped_as_llm_auth_failed(
        self, log_config: LogConfig
    ) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
        ):
            mock_key.side_effect = Exception("network error")
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(
                        models=[ModelConfig(model="gemini/gemini-2.0-flash", api_key="test-key")]
                    ),
                    log_config=log_config,
                )
        assert exc_info.value.code == "LLM_AUTH_FAILED"


# ── capability checks ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCapabilityChecks:
    def test_missing_structured_output_support_raises_llm_error(
        self, log_config: LogConfig
    ) -> None:
        params = [p for p in ALL_SUPPORTED_PARAMS if p != "response_format"]
        with patch("litellm.get_supported_openai_params") as mock_params:
            mock_params.return_value = params
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
                    log_config=log_config,
                )
        assert exc_info.value.code == "LLM_CAPABILITY_NOT_SUPPORTED"

    def test_missing_function_calling_support_raises_llm_error(
        self, log_config: LogConfig
    ) -> None:
        params = [p for p in ALL_SUPPORTED_PARAMS if p != "tools"]
        with patch("litellm.get_supported_openai_params") as mock_params:
            mock_params.return_value = params
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
                    log_config=log_config,
                )
        assert exc_info.value.code == "LLM_CAPABILITY_NOT_SUPPORTED"

    def test_capability_error_message_includes_model_and_capability_name(
        self, log_config: LogConfig
    ) -> None:
        params = [p for p in ALL_SUPPORTED_PARAMS if p != "response_format"]
        with patch("litellm.get_supported_openai_params") as mock_params:
            mock_params.return_value = params
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
                    log_config=log_config,
                )
        assert exc_info.value.message == (
            "Model 'gemini/gemini-2.0-flash' does not support structured output"
        )


# ── unsupported parameter check ───────────────────────────────────────────────


@pytest.mark.unit
class TestUnsupportedParameterCheck:
    def test_set_temperature_unsupported_raises_llm_error(
        self, log_config: LogConfig
    ) -> None:
        params = [p for p in ALL_SUPPORTED_PARAMS if p != "temperature"]
        with patch("litellm.get_supported_openai_params") as mock_params:
            mock_params.return_value = params
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(
                        models=[ModelConfig(model="gemini/gemini-2.0-flash", temperature=0.7)]
                    ),
                    log_config=log_config,
                )
        assert exc_info.value.code == "LLM_UNSUPPORTED_PARAMETER"

    def test_none_field_not_checked_against_supported_params(
        self, log_config: LogConfig
    ) -> None:
        params = [p for p in ALL_SUPPORTED_PARAMS if p != "temperature"]
        with patch("litellm.get_supported_openai_params") as mock_params:
            mock_params.return_value = params
            # temperature is None (default) — should not raise
            service = LLMService(
                profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
                log_config=log_config,
            )
        assert service is not None

    def test_unsupported_parameter_message_includes_model_and_param_name(
        self, log_config: LogConfig
    ) -> None:
        params = [p for p in ALL_SUPPORTED_PARAMS if p != "temperature"]
        with patch("litellm.get_supported_openai_params") as mock_params:
            mock_params.return_value = params
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=LLMProfile(
                        models=[ModelConfig(model="gemini/gemini-2.0-flash", temperature=0.7)]
                    ),
                    log_config=log_config,
                )
        assert exc_info.value.message == (
            "Model 'gemini/gemini-2.0-flash' does not support parameter 'temperature'"
        )


# ── log dir setup ─────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestLogDirSetup:
    def test_existing_log_dir_creates_successfully(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        service = LLMService(
            profile=minimal_profile,
            log_config=LogConfig(log_dir=log_dir),
        )
        assert service is not None

    def test_nonexistent_log_dir_is_created(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "new" / "logs"
        LLMService(
            profile=minimal_profile,
            log_config=LogConfig(log_dir=log_dir),
        )
        assert log_dir.is_dir()

    def test_log_dir_as_file_raises_llm_error(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.write_text("I am a file")
        with pytest.raises(LLMError) as exc_info:
            LLMService(
                profile=minimal_profile,
                log_config=LogConfig(log_dir=log_dir),
            )
        assert exc_info.value.code == "LLM_LOG_DIR_NOT_ACCESSIBLE"
        assert exc_info.value.message == (
            f"Log directory '{log_dir}' is not accessible: path exists as a file"
        )

    def test_ancestor_as_file_raises_llm_error(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "info"
        blocker.write_text("I am a file")
        log_dir = blocker / "logs"
        with pytest.raises(LLMError) as exc_info:
            LLMService(
                profile=minimal_profile,
                log_config=LogConfig(log_dir=log_dir),
            )
        assert exc_info.value.code == "LLM_LOG_DIR_NOT_ACCESSIBLE"
        assert exc_info.value.message == (
            f"Log directory '{log_dir}' is not accessible: an ancestor path is a file"
        )

    def test_unwritable_log_dir_raises_llm_error(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_dir.chmod(0o444)
        try:
            with pytest.raises(LLMError) as exc_info:
                LLMService(
                    profile=minimal_profile,
                    log_config=LogConfig(log_dir=log_dir),
                )
            assert exc_info.value.code == "LLM_LOG_DIR_NOT_ACCESSIBLE"
            assert exc_info.value.message == (
                f"Log directory '{log_dir}' is not accessible: permission denied"
            )
        finally:
            log_dir.chmod(0o755)


# ── clean_on_start ────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestCleanOnStart:
    def test_clean_on_start_true_clears_existing_log_file(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "llm.log"
        log_file.write_text("old content")
        LLMService(
            profile=minimal_profile,
            log_config=LogConfig(log_dir=log_dir, clean_on_start=True),
        )
        assert log_file.read_text() == ""

    def test_clean_on_start_false_preserves_existing_log_file(
        self, litellm_ok, minimal_profile: LLMProfile, tmp_path: Path
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "llm.log"
        log_file.write_text("old content")
        LLMService(
            profile=minimal_profile,
            log_config=LogConfig(log_dir=log_dir, clean_on_start=False),
        )
        assert log_file.read_text() == "old content"
