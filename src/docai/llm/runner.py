import asyncio
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

            # Validation retry loop (only for assistant message responses)
            validator = request.response_validator
            if (
                isinstance(result.response, LLMAssistantMessage)
                and validator is not None
            ):
                current_req = request
                for v in range(retry_policy.max_validation_retries + 1):
                    error = validator(result.response.content)  # type: ignore
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


def _status_code_matches(patterns: list[str], status_code: int) -> bool:
    for pattern in patterns:
        # Allow users to use "5xx" style patterns by converting them to regex
        regex_pattern = pattern.replace("x", r"\d").replace("X", r"\d")
        if re.fullmatch(regex_pattern, str(status_code)):
            return True
    return False
