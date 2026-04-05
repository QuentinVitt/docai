from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic.functional_validators import AfterValidator
from typing_extensions import Annotated


def _ge1_int(v: int) -> int:
    if v < 1:
        raise ValueError("must be >= 1")
    return v


def _ge0_float(v: float) -> float:
    if v < 0:
        raise ValueError("must be >= 0")
    return v


def _ge1_int_opt(v: int | None) -> int | None:
    if v is not None and v < 1:
        raise ValueError("must be >= 1")
    return v


def _ge0_float_opt(v: float | None) -> float | None:
    if v is not None and v < 0:
        raise ValueError("must be >= 0")
    return v


def _temperature_opt(v: float | None) -> float | None:
    if v is not None and not (0.0 <= v <= 2.0):
        raise ValueError("must be between 0.0 and 2.0")
    return v


def _unit_float_opt(v: float | None) -> float | None:
    if v is not None and not (0.0 <= v <= 1.0):
        raise ValueError("must be between 0.0 and 1.0")
    return v


def _penalty_opt(v: float | None) -> float | None:
    if v is not None and not (-2.0 <= v <= 2.0):
        raise ValueError("must be between -2.0 and 2.0")
    return v


class ModelConfig(BaseModel):
    # LiteLLM-passable fields
    model: str
    api_key: str | None = None
    base_url: str | None = None
    num_retries: Annotated[int | None, AfterValidator(_ge1_int_opt)] = None
    timeout: Annotated[float | None, AfterValidator(_ge0_float_opt)] = None
    temperature: Annotated[float | None, AfterValidator(_temperature_opt)] = None
    top_p: Annotated[float | None, AfterValidator(_unit_float_opt)] = None
    n: Annotated[int | None, AfterValidator(_ge1_int_opt)] = None
    max_completion_tokens: Annotated[int | None, AfterValidator(_ge1_int_opt)] = None
    max_tokens: Annotated[int | None, AfterValidator(_ge1_int_opt)] = None
    presence_penalty: Annotated[float | None, AfterValidator(_penalty_opt)] = None
    frequency_penalty: Annotated[float | None, AfterValidator(_penalty_opt)] = None
    extra_kwargs: dict[str, Any] = Field(default_factory=dict)

    # DocAI-internal fields
    validation_retries: Annotated[int, AfterValidator(_ge1_int)] = 3
    max_concurrency: Annotated[int, AfterValidator(_ge1_int)] = 5

    def to_litellm_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for passing directly to LiteLLM's acompletion.

        Explicit fields take precedence over same-named keys in extra_kwargs.
        None-valued fields are omitted so LiteLLM/provider defaults apply.
        validation_retries and max_concurrency are never included.
        """
        result: dict[str, Any] = dict(self.extra_kwargs)

        litellm_fields: list[tuple[str, Any]] = [
            ("model", self.model),
            ("api_key", self.api_key),
            ("base_url", self.base_url),
            ("num_retries", self.num_retries),
            ("timeout", self.timeout),
            ("temperature", self.temperature),
            ("top_p", self.top_p),
            ("n", self.n),
            ("max_completion_tokens", self.max_completion_tokens),
            ("max_tokens", self.max_tokens),
            ("presence_penalty", self.presence_penalty),
            ("frequency_penalty", self.frequency_penalty),
        ]

        for key, value in litellm_fields:
            if value is not None:
                result[key] = value

        return result

    def configured_params(self) -> set[str]:
        """Return the set of optional LiteLLM param names that are explicitly set (non-None)."""
        fields = [
            "num_retries", "timeout", "temperature", "top_p", "n",
            "max_completion_tokens", "max_tokens", "presence_penalty", "frequency_penalty",
        ]
        return {f for f in fields if getattr(self, f) is not None}


class LLMProfile(BaseModel):
    models: list[ModelConfig]
    max_concurrency: Annotated[int, AfterValidator(_ge1_int)] = 10
    skip_api_key_validation: bool = False

    @field_validator("models")
    @classmethod
    def models_not_empty(cls, v: list[ModelConfig]) -> list[ModelConfig]:
        if not v:
            raise ValueError("models list must not be empty")
        return v


class LogConfig(BaseModel):
    log_dir: Path
    clean_on_start: bool = False
