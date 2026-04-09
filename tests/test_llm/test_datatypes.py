import pytest
from pydantic import ValidationError

from docai.llm.datatypes import LLMProfile, ModelConfig


@pytest.mark.unit
class TestModelConfigConstruction:
    def test_creates_with_only_model(self) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash")
        assert config.model == "gemini/gemini-2.0-flash"

    def test_default_values(self) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash")
        assert config.validation_retries == 3
        assert config.max_concurrency == 5
        assert config.extra_kwargs == {}

    def test_all_fields_accessible(self) -> None:
        config = ModelConfig(
            model="gemini/gemini-2.0-flash",
            api_key="test-key",
            base_url="https://custom.endpoint/",
            num_retries=5,
            timeout=30.0,
            temperature=0.7,
            top_p=0.9,
            n=2,
            max_completion_tokens=1000,
            max_tokens=2000,
            presence_penalty=0.1,
            frequency_penalty=0.2,
            extra_kwargs={"thinking": {"type": "enabled"}},
            validation_retries=5,
            max_concurrency=10,
        )
        assert config.model == "gemini/gemini-2.0-flash"
        assert config.api_key == "test-key"
        assert config.base_url == "https://custom.endpoint/"
        assert config.num_retries == 5
        assert config.timeout == 30.0
        assert config.temperature == 0.7
        assert config.top_p == 0.9
        assert config.n == 2
        assert config.max_completion_tokens == 1000
        assert config.max_tokens == 2000
        assert config.presence_penalty == 0.1
        assert config.frequency_penalty == 0.2
        assert config.extra_kwargs == {"thinking": {"type": "enabled"}}
        assert config.validation_retries == 5
        assert config.max_concurrency == 10

    def test_missing_model_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            ModelConfig()  # type: ignore[call-arg]


@pytest.mark.unit
class TestModelConfigFieldValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("timeout", -0.1),
            ("num_retries", 0),
            ("validation_retries", 0),
            ("max_concurrency", 0),
            ("n", 0),
            ("max_completion_tokens", 0),
            ("max_tokens", 0),
            ("temperature", -0.1),
            ("temperature", 2.1),
            ("top_p", -0.1),
            ("top_p", 1.1),
            ("presence_penalty", -2.1),
            ("presence_penalty", 2.1),
            ("frequency_penalty", -2.1),
            ("frequency_penalty", 2.1),
        ],
    )
    def test_invalid_field_value_raises_validation_error(
        self, field: str, value: float
    ) -> None:
        with pytest.raises(ValidationError):
            ModelConfig(model="gemini/gemini-2.0-flash", **{field: value})

    @pytest.mark.parametrize(
        "field,value",
        [
            ("timeout", 0.0),
            ("num_retries", 1),
            ("validation_retries", 1),
            ("max_concurrency", 1),
            ("n", 1),
            ("max_completion_tokens", 1),
            ("max_tokens", 1),
            ("temperature", 0.0),
            ("temperature", 2.0),
            ("top_p", 0.0),
            ("top_p", 1.0),
            ("presence_penalty", -2.0),
            ("presence_penalty", 2.0),
            ("frequency_penalty", -2.0),
            ("frequency_penalty", 2.0),
        ],
    )
    def test_boundary_values_are_valid(self, field: str, value: float) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash", **{field: value})
        assert getattr(config, field) == value


@pytest.mark.unit
class TestToLitellmKwargs:
    def test_only_model_set(self) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash")
        assert config.to_litellm_kwargs() == {"model": "gemini/gemini-2.0-flash"}

    def test_all_optional_litellm_fields_included(self) -> None:
        config = ModelConfig(
            model="gemini/gemini-2.0-flash",
            api_key="test-key",
            base_url="https://custom.endpoint/",
            num_retries=5,
            timeout=30.0,
            temperature=0.7,
            top_p=0.9,
            n=2,
            max_completion_tokens=1000,
            max_tokens=2000,
            presence_penalty=0.1,
            frequency_penalty=0.2,
        )
        assert config.to_litellm_kwargs() == {
            "model": "gemini/gemini-2.0-flash",
            "api_key": "test-key",
            "base_url": "https://custom.endpoint/",
            "num_retries": 5,
            "timeout": 30.0,
            "temperature": 0.7,
            "top_p": 0.9,
            "n": 2,
            "max_completion_tokens": 1000,
            "max_tokens": 2000,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.2,
        }

    def test_none_fields_excluded(self) -> None:
        config = ModelConfig(
            model="gemini/gemini-2.0-flash",
            api_key=None,
            temperature=None,
            timeout=None,
        )
        result = config.to_litellm_kwargs()
        assert "api_key" not in result
        assert "temperature" not in result
        assert "timeout" not in result

    def test_falsy_non_none_values_included(self) -> None:
        config = ModelConfig(
            model="gemini/gemini-2.0-flash",
            temperature=0.0,
            presence_penalty=0.0,
        )
        result = config.to_litellm_kwargs()
        assert result["temperature"] == 0.0
        assert result["presence_penalty"] == 0.0

    def test_validation_retries_not_in_output(self) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash", validation_retries=7)
        assert "validation_retries" not in config.to_litellm_kwargs()

    def test_max_concurrency_not_in_output(self) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash", max_concurrency=20)
        assert "max_concurrency" not in config.to_litellm_kwargs()

    def test_extra_kwargs_flattened_to_top_level(self) -> None:
        config = ModelConfig(
            model="gemini/gemini-2.0-flash",
            extra_kwargs={"thinking": {"type": "enabled"}, "custom_param": "value"},
        )
        result = config.to_litellm_kwargs()
        assert result["thinking"] == {"type": "enabled"}
        assert result["custom_param"] == "value"

    def test_empty_extra_kwargs_adds_no_keys(self) -> None:
        config = ModelConfig(model="gemini/gemini-2.0-flash", extra_kwargs={})
        assert config.to_litellm_kwargs() == {"model": "gemini/gemini-2.0-flash"}

    def test_explicit_field_takes_precedence_over_extra_kwargs(self) -> None:
        config = ModelConfig(
            model="gemini/gemini-2.0-flash",
            temperature=0.7,
            extra_kwargs={"temperature": 0.9},
        )
        assert config.to_litellm_kwargs()["temperature"] == 0.7


@pytest.mark.unit
class TestLLMProfileConstruction:
    def test_creates_with_one_model(self) -> None:
        model = ModelConfig(model="gemini/gemini-2.0-flash")
        profile = LLMProfile(models=[model])
        assert profile.models[0].model == "gemini/gemini-2.0-flash"

    def test_multiple_models_preserved_in_order(self) -> None:
        model_a = ModelConfig(model="gemini/gemini-2.0-flash")
        model_b = ModelConfig(model="gemini/gemini-2.0-pro")
        model_c = ModelConfig(model="openai/gpt-4o")
        profile = LLMProfile(models=[model_a, model_b, model_c])
        assert profile.models[0].model == "gemini/gemini-2.0-flash"
        assert profile.models[1].model == "gemini/gemini-2.0-pro"
        assert profile.models[2].model == "openai/gpt-4o"

    def test_default_max_concurrency(self) -> None:
        profile = LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")])
        assert profile.max_concurrency == 10

    def test_default_skip_api_key_validation(self) -> None:
        profile = LLMProfile(models=[ModelConfig(model="gemini/gemini-2.0-flash")])
        assert profile.skip_api_key_validation is False

    def test_empty_models_list_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            LLMProfile(models=[])

    def test_missing_models_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            LLMProfile()  # type: ignore[call-arg]


@pytest.mark.unit
class TestLLMProfileFieldValidation:
    def test_max_concurrency_zero_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            LLMProfile(
                models=[ModelConfig(model="gemini/gemini-2.0-flash")], max_concurrency=0
            )

    def test_max_concurrency_one_is_valid(self) -> None:
        profile = LLMProfile(
            models=[ModelConfig(model="gemini/gemini-2.0-flash")], max_concurrency=1
        )
        assert profile.max_concurrency == 1
