import asyncio
import random
import re
from logging import getLogger

from docai.llm.cache import LLMCache
from docai.llm.client import LLMClient
from docai.llm.datatypes import LLMModelConfig, LLMRequest, LLMResponse, LLMRetryConfig
from docai.llm.errors import LLMError

logger = getLogger("docai_project")


async def run(
    cache: LLMCache,
    request: LLMRequest,
    model_config: LLMModelConfig,
    client: LLMClient,
    retry_policy: LLMRetryConfig,
    semaphore: asyncio.Semaphore,
) -> LLMResponse:
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
        except Exception as e:
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
