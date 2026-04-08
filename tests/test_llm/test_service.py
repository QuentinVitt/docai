from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

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
    with (
        patch("litellm.get_supported_openai_params") as mock_params,
        patch("litellm.supports_response_schema") as mock_schema,
    ):
        mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
        mock_schema.return_value = True
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
            patch("litellm.supports_response_schema") as mock_schema,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            mock_schema.return_value = True
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
            patch("litellm.supports_response_schema") as mock_schema,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            mock_schema.return_value = True
            LLMService(
                profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
                log_config=log_config,
            )
        mock_key.assert_not_called()

    def test_check_valid_key_skipped_when_base_url_set(self, log_config: LogConfig) -> None:
        with (
            patch("litellm.check_valid_key") as mock_key,
            patch("litellm.get_supported_openai_params") as mock_params,
            patch("litellm.supports_response_schema") as mock_schema,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            mock_schema.return_value = True
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
            patch("litellm.supports_response_schema") as mock_schema,
        ):
            mock_key.return_value = True
            mock_params.return_value = list(ALL_SUPPORTED_PARAMS)
            mock_schema.return_value = True
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
        with (
            patch("litellm.get_supported_openai_params") as mock_params,
            patch("litellm.supports_response_schema") as mock_schema,
        ):
            mock_params.return_value = params
            mock_schema.return_value = True
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


# ── generate() helpers and fixtures ──────────────────────────────────────────


def _make_llm_response(content: str = "Hello, world!") -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15
    usage.completion_tokens_details = None

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = "gemini/gemini-2.0-flash"
    return response


class _SimpleOutput(BaseModel):
    value: str


@pytest.fixture
def generate_service(litellm_ok, log_config: LogConfig) -> LLMService:
    profile = LLMProfile(
        models=[ModelConfig(model="gemini/gemini-2.0-flash", validation_retries=3)],
    )
    return LLMService(profile=profile, log_config=log_config)


@pytest.fixture
def two_model_service(litellm_ok, log_config: LogConfig) -> LLMService:
    profile = LLMProfile(
        models=[
            ModelConfig(model="gemini/gemini-2.0-flash", validation_retries=2),
            ModelConfig(model="gemini/gemini-2.0-pro", validation_retries=2),
        ],
    )
    return LLMService(profile=profile, log_config=log_config)


# ── generate() — happy path ───────────────────────────────────────────────────


@pytest.mark.llm
class TestGenerateHappyPath:
    async def test_plain_prompt_returns_string(self, generate_service: LLMService) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response("Hello, world!")
            result = await generate_service.generate(prompt="test prompt")
        assert result == "Hello, world!"

    async def test_structured_output_returns_pydantic_instance(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response('{"value": "parsed"}')
            result = await generate_service.generate(
                prompt="test", structured_output=_SimpleOutput
            )
        assert result == _SimpleOutput(value="parsed")

    async def test_structured_output_passes_response_format_to_acompletion(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response('{"value": "x"}')
            await generate_service.generate(prompt="test", structured_output=_SimpleOutput)
        assert mock_ac.call_args.kwargs["response_format"] == _SimpleOutput

    async def test_prompt_sent_as_user_message(self, generate_service: LLMService) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="my question")
        assert mock_ac.call_args.kwargs["messages"] == [
            {"role": "user", "content": "my question"}
        ]

    async def test_connection_kwargs_forwarded_to_acompletion(
        self, generate_service: LLMService
    ) -> None:
        expected_kwargs = generate_service._connections[0][0]
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="test")
        actual_kwargs = mock_ac.call_args.kwargs
        for key, value in expected_kwargs.items():
            assert actual_kwargs[key] == value

    async def test_system_prompt_prepended_as_system_message(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="my question", system_prompt="You are helpful.")
        assert mock_ac.call_args.kwargs["messages"] == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "my question"},
        ]


# ── generate() — validator ────────────────────────────────────────────────────


@pytest.mark.llm
class TestGenerateValidator:
    async def test_no_validator_calls_acompletion_once(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="test")
        assert mock_ac.call_count == 1

    async def test_validator_passes_first_try_calls_acompletion_once(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="test", validator=lambda _: None)
        assert mock_ac.call_count == 1

    async def test_validator_fails_once_then_passes_calls_acompletion_twice(
        self, generate_service: LLMService
    ) -> None:
        call_count = 0

        async def fake_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            return _make_llm_response()

        def validator(output: str) -> str | None:
            return "not good" if call_count == 1 else None

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            await generate_service.generate(prompt="test", validator=validator)

        assert call_count == 2

    async def test_validator_failure_appended_to_retry_messages(
        self, generate_service: LLMService
    ) -> None:
        call_count = 0
        captured_messages: list[list[dict]] = []

        async def fake_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            captured_messages.append(kwargs["messages"])
            return _make_llm_response("first response")

        def validator(output: str) -> str | None:
            return "output was invalid" if call_count == 1 else None

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            await generate_service.generate(prompt="original prompt", validator=validator)

        assert captured_messages[1] == [
            {"role": "user", "content": "original prompt"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "output was invalid"},
        ]

    async def test_system_prompt_preserved_in_retry_messages(
        self, generate_service: LLMService
    ) -> None:
        call_count = 0
        captured_messages: list[list[dict]] = []

        async def fake_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            captured_messages.append(kwargs["messages"])
            return _make_llm_response("first response")

        def validator(output: str) -> str | None:
            return "try again" if call_count == 1 else None

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            await generate_service.generate(
                prompt="my question",
                system_prompt="You are helpful.",
                validator=validator,
            )

        assert captured_messages[1] == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "my question"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "try again"},
        ]

    async def test_validator_fails_all_retries_falls_back_to_second_connection(
        self, two_model_service: LLMService
    ) -> None:
        first_model_calls = 0

        async def fake_acompletion(**kwargs):
            nonlocal first_model_calls
            if kwargs.get("model") == "gemini/gemini-2.0-flash":
                first_model_calls += 1
                return _make_llm_response("bad")
            return _make_llm_response("good")

        def validator(output: str) -> str | None:
            return "rejected" if output == "bad" else None

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            result = await two_model_service.generate(prompt="test", validator=validator)

        assert first_model_calls == 2  # exhausted validation_retries=2
        assert result == "good"


# ── generate() — fallback and errors ─────────────────────────────────────────


@pytest.mark.llm
class TestGenerateFallback:
    async def test_api_exception_triggers_fallback_to_next_connection(
        self, two_model_service: LLMService
    ) -> None:
        async def fake_acompletion(**kwargs):
            if kwargs.get("model") == "gemini/gemini-2.0-flash":
                raise Exception("first model down")
            return _make_llm_response("second model response")

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            result = await two_model_service.generate(prompt="test")

        assert result == "second model response"

    async def test_all_connections_exhausted_raises_llm_error(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.side_effect = Exception("API error")
            with pytest.raises(LLMError) as exc_info:
                await generate_service.generate(prompt="test")

        assert exc_info.value.code == "LLM_ALL_MODELS_FAILED"

    async def test_all_models_failed_error_message(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.side_effect = Exception("API error")
            with pytest.raises(LLMError) as exc_info:
                await generate_service.generate(prompt="test")

        assert exc_info.value.message == "All models failed to produce a valid response"


# ── generate() — structured output parsing ───────────────────────────────────


@pytest.mark.llm
class TestGenerateStructuredOutputParsing:
    async def test_unparseable_response_retries_then_raises(
        self, generate_service: LLMService
    ) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response("not valid json")
            with pytest.raises(LLMError) as exc_info:
                await generate_service.generate(
                    prompt="test", structured_output=_SimpleOutput
                )

        assert mock_ac.call_count == 3  # validation_retries=3, all fail to parse
        assert exc_info.value.code == "LLM_ALL_MODELS_FAILED"


# ── generate() — semaphores ───────────────────────────────────────────────────


@pytest.mark.llm
class TestGenerateSemaphores:
    async def test_global_semaphore_restored_after_successful_call(
        self, generate_service: LLMService
    ) -> None:
        initial = generate_service._global_semaphore._value
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="test")
        assert generate_service._global_semaphore._value == initial

    async def test_per_model_semaphore_restored_after_successful_call(
        self, generate_service: LLMService
    ) -> None:
        _, _, semaphore = generate_service._connections[0]
        initial = semaphore._value
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await generate_service.generate(prompt="test")
        assert semaphore._value == initial

    async def test_semaphores_restored_after_acompletion_raises(
        self, generate_service: LLMService
    ) -> None:
        global_initial = generate_service._global_semaphore._value
        _, _, semaphore = generate_service._connections[0]
        model_initial = semaphore._value
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.side_effect = Exception("API error")
            with pytest.raises(LLMError):
                await generate_service.generate(prompt="test")
        assert generate_service._global_semaphore._value == global_initial
        assert semaphore._value == model_initial


# ── generate() — logging ─────────────────────────────────────────────────────


@pytest.mark.integration
class TestGenerateLogging:
    async def test_successful_generate_writes_one_json_line(
        self, litellm_ok, log_config: LogConfig, log_dir: Path
    ) -> None:
        service = LLMService(
            profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
            log_config=log_config,
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response("result")
            await service.generate(prompt="test")

        lines = (log_dir / "llm.log").read_text().strip().splitlines()
        assert len(lines) == 1
        json.loads(lines[0])  # must be valid JSON

    async def test_log_entry_success_true_with_final_response(
        self, litellm_ok, log_config: LogConfig, log_dir: Path
    ) -> None:
        service = LLMService(
            profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
            log_config=log_config,
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response("the answer")
            await service.generate(prompt="test")

        entry = json.loads((log_dir / "llm.log").read_text().strip())
        assert entry["success"] is True
        assert entry["final_response"] == "the answer"

    async def test_log_entry_has_one_attempt_for_single_successful_call(
        self, litellm_ok, log_config: LogConfig, log_dir: Path
    ) -> None:
        service = LLMService(
            profile=LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")]),
            log_config=log_config,
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await service.generate(prompt="test")

        entry = json.loads((log_dir / "llm.log").read_text().strip())
        assert len(entry["attempts"]) == 1

    async def test_failed_generate_still_writes_log_entry(
        self, litellm_ok, log_config: LogConfig, log_dir: Path
    ) -> None:
        service = LLMService(
            profile=LLMProfile(
                models=[ModelConfig(model="gemini/gemini-2.0-flash", validation_retries=1)]
            ),
            log_config=log_config,
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.side_effect = Exception("API down")
            with pytest.raises(LLMError):
                await service.generate(prompt="test")

        lines = (log_dir / "llm.log").read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["success"] is False

    async def test_api_key_masked_as_redacted_in_log_model_args(
        self, litellm_ok, log_config: LogConfig, log_dir: Path
    ) -> None:
        service = LLMService(
            profile=LLMProfile(
                models=[ModelConfig(model="gemini/gemini-2.0-flash", api_key="secret-key-123")],
                skip_api_key_validation=True,
            ),
            log_config=log_config,
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _make_llm_response()
            await service.generate(prompt="test")

        entry = json.loads((log_dir / "llm.log").read_text().strip())
        assert entry["attempts"][0]["model_args"]["api_key"] == "[REDACTED]"
