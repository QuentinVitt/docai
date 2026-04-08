from __future__ import annotations

import asyncio
import os
import time
from logging import getLogger
from pathlib import Path
from typing import Callable

import litellm
from litellm import BadRequestError, openai
from pydantic import BaseModel

from docai.llm.datatypes import (
    LLMCallAttempt,
    LLMGenerateLog,
    LLMProfile,
    LogConfig,
    ModelConfig,
)
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
            self._connections.append(
                (
                    model.to_litellm_kwargs(),
                    model.validation_retries,
                    asyncio.Semaphore(effective),
                )
            )

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
        supported = set(
            litellm.get_supported_openai_params(
                model=model.model, custom_llm_provider=model.base_url
            )
            or []
        )

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

        if not litellm.supports_response_schema(
            model=model.model, custom_llm_provider=model.base_url
        ):
            raise LLMError(
                code="LLM_UNSUPPORTED_PARAMETER",
                message=f"Model '{model.model}' does not support response schema [{litellm.supports_response_schema(model=model.model, custom_llm_provider=model.base_url)}]",
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

    async def _call(
        self,
        model_args: dict,
        messages: list[dict | litellm.Message],
        model_semaphore: asyncio.Semaphore,
        *,
        structured_output: type[BaseModel] | None = None,
    ) -> tuple[litellm.Message | Exception, litellm.Usage | None]:

        call_args = model_args.copy()
        try:
            async with self._global_semaphore:
                async with model_semaphore:
                    if structured_output:
                        call_args["response_format"] = structured_output
                    call_args["messages"] = messages
                    response = await litellm.acompletion(**call_args)
                    if isinstance(response, litellm.CustomStreamWrapper):
                        raise LLMError(
                            code="LLM_STREAMING_NOT_SUPPORTED",
                            message="Streaming is not for docai",
                        )
                    return response.choices[0].message, response.usage  # type: ignore
        except openai.OpenAIError as e:
            return e, None

    def _log_attempt(
        self,
        *,
        model_args: dict,
        latency: float,
        usage: litellm.Usage | None = None,
        messages: list[dict | litellm.Message],
        response: litellm.Message | None = None,
        validation_error: str | None = None,
        error: str | None = None,
    ) -> LLMCallAttempt:
        raise NotImplementedError
        if model_args["api_key"]:
            model_args["api_key"] = "[REDACTED]"

    async def _log(
        self,
        *,
        latency: float,
        success: bool,
        attempts: list[LLMCallAttempt],
        final_response: litellm.Message | None = None,
        error_code: str | None = None,
    ):
        raise NotImplementedError

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        structured_output: type[BaseModel] | None = None,
        validator: Callable[[str | BaseModel], str | None] | None = None,
    ) -> str | BaseModel:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        log_attempts: list[LLMCallAttempt] = []
        generation_start = time.perf_counter()
        success = False
        final_response: litellm.Message | None = None
        error_code: str | None = None

        try:
            for model_args, val_retries, model_semaphore in self._connections:
                try_messages: list[dict | litellm.Message] = list(messages)

                for _ in range(val_retries):
                    call_start = time.perf_counter()
                    resp_message, usage = await self._call(
                        model_args,
                        try_messages,
                        model_semaphore,
                        structured_output=structured_output,
                    )
                    call_latency = time.perf_counter() - call_start

                    if isinstance(resp_message, Exception):
                        log_attempts.append(
                            self._log_attempt(
                                model_args=model_args,
                                latency=call_latency,
                                messages=try_messages,
                                error=str(resp_message),
                            )
                        )
                        logger.info(f"LLM call error: {resp_message}")
                        break  # move to next connection

                    if resp_message.role != "assistant" or resp_message.content is None:
                        detail = (
                            f"Unexpected role: {resp_message.role}"
                            if resp_message.role != "assistant"
                            else "Unexpected content: None"
                        )
                        log_attempts.append(
                            self._log_attempt(
                                model_args=model_args,
                                latency=call_latency,
                                usage=usage,
                                messages=try_messages,
                                response=resp_message,
                                error=detail,
                            )
                        )
                        logger.info(f"LLM response error: {detail}")
                        break  # move to next connection

                    resp_content = resp_message.content

                    if structured_output:
                        try:
                            resp_content = structured_output.model_validate_json(
                                resp_content
                            )
                        except Exception as e:
                            log_attempts.append(
                                self._log_attempt(
                                    model_args=model_args,
                                    latency=call_latency,
                                    usage=usage,
                                    messages=try_messages,
                                    response=resp_message,
                                    validation_error=str(e),
                                )
                            )
                            try_messages = [
                                *try_messages,
                                resp_message,
                                {
                                    "role": "user",
                                    "content": f"Response could not be parsed.\nError: {e}",
                                },
                            ]
                            continue  # retry with parse error fed back

                    if validator and (val_error := validator(resp_content)):
                        log_attempts.append(
                            self._log_attempt(
                                model_args=model_args,
                                latency=call_latency,
                                usage=usage,
                                messages=try_messages,
                                response=resp_message,
                                validation_error=val_error,
                            )
                        )
                        try_messages = [
                            *try_messages,
                            resp_message,
                            {"role": "user", "content": val_error},
                        ]
                        continue  # retry with validator error fed back

                    # Success
                    log_attempts.append(
                        self._log_attempt(
                            model_args=model_args,
                            latency=call_latency,
                            usage=usage,
                            messages=try_messages,
                            response=resp_message,
                        )
                    )
                    success = True
                    final_response = resp_message
                    return resp_content  # finally still runs before returning

                logger.debug(
                    f"Connection '{model_args.get('model')}' exhausted all retries"
                )

            # All connections exhausted
            error_code = "LLM_ALL_MODELS_FAILED"
            raise LLMError(
                code="LLM_ALL_MODELS_FAILED",
                message="All models failed to produce a valid response",
            )

        finally:
            await self._log(
                latency=time.perf_counter() - generation_start,
                success=success,
                attempts=log_attempts,
                final_response=final_response,
                error_code=error_code,
            )
