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
    LLMSystemMessage,
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
) -> LLMResponse:
    for attempt in range(retry_policy.max_retries):
        try:
            async with semaphore:
                result = await client.generate(request, model_config)

            if isinstance(result.response, LLMAssistantMessage):
                result = await _validate_response(
                    client, model_config, request, result, retry_policy, semaphore
                )

            return result

        except LLMError as e:
            if not _status_code_matches(retry_policy.retry_on, e.status_code):
                raise
            logger.debug(
                "Request %s failed on attempt %d with status %s: %s",
                request.id,
                attempt + 1,
                e.status_code,
                e.response,
            )

        except Exception as e:
            logger.debug(
                "Request %s failed on attempt %d with unexpected error: %s",
                request.id,
                attempt + 1,
                e,
            )

        delay = retry_policy.retry_delay * (2**attempt) + random.uniform(0, 1)
        logger.debug("Retrying request %s in %.2f seconds...", request.id, delay)
        await asyncio.sleep(delay)

    raise LLMError(
        611,
        f"All {retry_policy.max_retries} attempts failed for request {request.id}",
    )


async def _validate_response(
    client: LLMClient,
    model_config: LLMModelConfig,
    request: LLMRequest,
    result: LLMResponse,
    retry_policy: LLMRetryConfig,
    semaphore: asyncio.Semaphore,
) -> LLMResponse:
    """Parse JSON and run the response validator, retrying with feedback on error."""
    current_req = request
    for attempt in range(retry_policy.max_validation_retries + 1):
        error: str | None = None

        if request.structured_output is not None and isinstance(
            result.response.content,  # type: ignore
            str,
        ):  # type: ignore
            parsed = _parse_structured_response(result)
            if isinstance(parsed, str):
                error = parsed
            else:
                result = parsed

        if error is None and request.response_validator is not None:
            error = request.response_validator(result.response.content)  # type: ignore

        if error is None:
            return result

        if attempt == retry_policy.max_validation_retries:
            raise LLMError(
                613,
                f"Validation failed after {retry_policy.max_validation_retries} retries for request {request.id}: {error}",
            )

        current_req = LLMRequest(
            prompt=LLMSystemMessage(
                content=f"Your previous response was invalid. Fix the following issue and try again: {error}"
            ),
            system_prompt=current_req.system_prompt,
            history=list(current_req.history) + [current_req.prompt, result.response],
            allowed_tools=current_req.allowed_tools,
            structured_output=current_req.structured_output,
            id=current_req.id,
            response_validator=current_req.response_validator,
        )
        async with semaphore:
            result = await client.generate(current_req, model_config)

    return result


def _parse_structured_response(result: LLMResponse) -> LLMResponse | str:
    """Parse JSON from a text response.

    Returns a new LLMResponse with parsed content on success, or an error string on failure.
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
            return f"Response is not valid JSON: {e}"
    return LLMResponse(
        response=LLMAssistantMessage(
            content=parsed,
            original_content=result.response.original_content,
        ),
        id=result.id,
    )


def _status_code_matches(patterns: list[str], status_code: int) -> bool:
    for pattern in patterns:
        # Allow users to use "5xx" style patterns by converting them to regex
        regex_pattern = pattern.replace("x", r"\d").replace("X", r"\d")
        if re.fullmatch(regex_pattern, str(status_code)):
            return True
    return False
