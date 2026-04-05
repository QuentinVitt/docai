from __future__ import annotations

import asyncio
import os
from logging import getLogger
from pathlib import Path

import litellm

from docai.llm.datatypes import LLMProfile, LogConfig, ModelConfig
from docai.llm.errors import LLMError

logger = getLogger(__name__)

LOG_FILE_NAME = "llm.log"

_CAPABILITY_NAMES: dict[str, str] = {
    "response_format": "structured output",
    "tools": "function calling",
}


class LLMService:
    def __init__(self, profile: LLMProfile, log_config: LogConfig) -> None:
        self._setup_log_dir(log_config)
        self._global_semaphore = asyncio.Semaphore(profile.max_concurrency)
        self._connections: list[tuple[dict, int, asyncio.Semaphore]] = []

        for model in profile.models:
            self._validate_model(model, profile)
            effective = min(model.max_concurrency, profile.max_concurrency)
            if model.max_concurrency > profile.max_concurrency:
                logger.debug(
                    f"Model '{model.model}': max_concurrency {model.max_concurrency} "
                    f"exceeds profile limit {profile.max_concurrency}, "
                    f"capping to {profile.max_concurrency}"
                )
            self._connections.append((model.to_litellm_kwargs(), model.validation_retries, asyncio.Semaphore(effective)))

    def _validate_model(self, model: ModelConfig, profile: LLMProfile) -> None:
        # API key validation (only when key is in config and no custom base_url)
        if not profile.skip_api_key_validation and model.api_key and not model.base_url:
            try:
                valid = litellm.check_valid_key(model.model, model.api_key)
            except Exception:
                valid = False
            if not valid:
                raise LLMError(
                    code="LLM_AUTH_FAILED",
                    message=f"API key validation failed for model '{model.model}'",
                )

        # Capability and parameter checks
        supported = set(litellm.get_supported_openai_params(model=model.model) or [])

        for capability in ("response_format", "tools"):
            if capability not in supported:
                raise LLMError(
                    code="LLM_CAPABILITY_NOT_SUPPORTED",
                    message=f"Model '{model.model}' does not support {_CAPABILITY_NAMES[capability]}",
                )

        for param in model.configured_params():
            if param not in supported:
                raise LLMError(
                    code="LLM_UNSUPPORTED_PARAMETER",
                    message=f"Model '{model.model}' does not support parameter '{param}'",
                )

    def _setup_log_dir(self, log_config: LogConfig) -> None:
        path = Path(log_config.log_dir)

        # Reject if the target path itself is a file
        if path.exists() and not path.is_dir():
            raise LLMError(
                code="LLM_LOG_DIR_NOT_ACCESSIBLE",
                message=f"Log directory '{path}' is not accessible: path exists as a file",
            )

        # Reject if any ancestor component is a file
        for ancestor in path.parents:
            if ancestor.exists() and not ancestor.is_dir():
                raise LLMError(
                    code="LLM_LOG_DIR_NOT_ACCESSIBLE",
                    message=f"Log directory '{path}' is not accessible: an ancestor path is a file",
                )

        # Create directory tree if needed
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise LLMError(
                code="LLM_LOG_DIR_NOT_ACCESSIBLE",
                message=f"Log directory '{path}' is not accessible: permission denied",
            )

        # Check write permission on existing directory
        if not os.access(path, os.W_OK):
            raise LLMError(
                code="LLM_LOG_DIR_NOT_ACCESSIBLE",
                message=f"Log directory '{path}' is not accessible: permission denied",
            )

        # Create or truncate the log file
        log_file = path / LOG_FILE_NAME
        mode = "w" if log_config.clean_on_start else "a"
        log_file.open(mode).close()
