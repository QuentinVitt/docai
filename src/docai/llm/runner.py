import asyncio
import json
import random
import re
from logging import getLogger

from docai.config.datatypes import LLMModelConfig, LLMRetryConfig
from docai.llm.cache import LLMCache
from docai.llm.client import LLMClient
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMRequest,
    LLMResponse,
    LLMUserMessage,
)
from docai.llm.errors import LLMError

logger = getLogger(__name__)


async def run(
    cache: LLMCache,
    request: LLMRequest,
    model_config: LLMModelConfig,
    client: LLMClient,
    retry_policy: LLMRetryConfig,
    semaphore: asyncio.Semaphore,
    bypass_cache: bool = False,
) -> LLMResponse:
    if not bypass_cache:
        result = cache.get(request, model_config)
        if result:
            return result

    result = await _run(client, request, model_config, retry_policy, semaphore)

    cache.put(request, model_config, result)

    return result


async def _run(
    client: LLMClient,
    request: LLMRequest,
    model_config: LLMModelConfig,
    retry_policy: LLMRetryConfig,
    semaphore: asyncio.Semaphore,
):
    for t in range(retry_policy.max_retries):
        try:
            async with semaphore:
                result = await client.generate(request, model_config)

            # Validation retry loop: parse JSON + run validator, feeding errors back
            if isinstance(result.response, LLMAssistantMessage):
                validator = request.response_validator
                needs_json = (
                    request.structured_output is not None
                    and isinstance(result.response.content, str)
                )
                if needs_json or validator is not None:
                    current_req = request
                    for v in range(retry_policy.max_validation_retries + 1):
                        # Step 1: parse JSON if needed
                        error: str | None = None
                        if (
                            request.structured_output is not None
                            and isinstance(result.response.content, str)
                        ):
                            result, error = _parse_structured_response(result)

                        # Step 2: run validator if JSON parsed successfully
                        if error is None and validator is not None:
                            error = validator(result.response.content)

                        if error is None:
                            break
                        if v == retry_policy.max_validation_retries:
                            logger.error(
                                "Validation exhausted for request %s after %d retries: %s",
                                request.id,
                                retry_policy.max_validation_retries,
                                error,
                            )
                            raise LLMError(
                                613,
                                f"Validation failed after {retry_policy.max_validation_retries} retries for request {request.id}: {error}",
                            )
                        logger.warning(
                            "Validation retry %d for request %s: %s",
                            v + 1,
                            request.id,
                            error,
                        )
                        current_req = LLMRequest(
                            prompt=LLMUserMessage(
                                content=f"Your previous response was invalid. Fix the following issue and try again: {error}"
                            ),
                            system_prompt=current_req.system_prompt,
                            history=list(current_req.history)
                            + [current_req.prompt, result.response],
                            allowed_tools=current_req.allowed_tools,
                            structured_output=current_req.structured_output,
                            id=current_req.id,
                            response_validator=current_req.response_validator,
                        )
                        async with semaphore:
                            result = await client.generate(current_req, model_config)

            return result
        except LLMError as e:
            logger.error(
                "Failed to get result from llm for request: %s in try: %d. Status: %s",
                request.id,
                t + 1,
                e.status_code,
            )
            if _status_code_matches(
                patterns=retry_policy.retry_on, status_code=e.status_code
            ):
                sleep_time = retry_policy.retry_delay * (2**t) + random.uniform(0, 1)
                logger.info(
                    "Retrying request %s in %.2f seconds...", request.id, sleep_time
                )
                await asyncio.sleep(sleep_time)
                continue
            raise e
        except Exception:
            logger.error(
                "Unexpected network or parsing error for request: %s in try: %d",
                request.id,
                t + 1,
                exc_info=True,
            )
            # Default to retrying on unexpected network/client drops
            sleep_time = retry_policy.retry_delay * (2**t) + random.uniform(0, 1)
            logger.info(
                "Retrying request %s in %.2f seconds...", request.id, sleep_time
            )
            await asyncio.sleep(sleep_time)

    logger.error(
        "Failed to generate result for llm for request: %s. All tries failed",
        request.id,
    )
    raise LLMError(
        611,
        f"Failed to generate result for llm for request: {request.id}. All tries failed",
    )


def _parse_structured_response(result: LLMResponse) -> tuple[LLMResponse, str | None]:
    """Parse JSON from a text response.

    Returns (new_response, None) on success, or (original_response, error_msg) on failure.
    """
    assert isinstance(result.response, LLMAssistantMessage)
    text = result.response.content
    assert isinstance(text, str)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Strip markdown fences and retry
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as e:
            return result, f"Response is not valid JSON: {e}"
    return LLMResponse(
        response=LLMAssistantMessage(
            content=parsed,
            original_content=result.response.original_content,
        ),
        id=result.id,
    ), None


def _status_code_matches(patterns: list[str], status_code: int) -> bool:
    for pattern in patterns:
        # Allow users to use "5xx" style patterns by converting them to regex
        regex_pattern = pattern.replace("x", r"\d").replace("X", r"\d")
        if re.fullmatch(regex_pattern, str(status_code)):
            return True
    return False
