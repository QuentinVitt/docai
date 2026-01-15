import asyncio
import logging
import re
from typing import AsyncIterable, AsyncIterator, Optional

from docai.llm.llm_client import LLMClient
from docai.llm.llm_datatypes import (
    LLMError,
    LLMExecutionPlan,
    LLMRequest,
    LLMResponse,
    LLMTarget,
)

logger = logging.getLogger("docai_project")

clients: dict[str, LLMClient] = {}


def _status_code_matches(patterns: list[str], status_code: int) -> bool:
    for pattern in patterns:
        if re.fullmatch(pattern.replace("x", "\\d"), str(status_code)):
            return True
    return False


async def run_request(execution_plan: LLMExecutionPlan) -> LLMResponse:
    last_error: Optional[LLMError] = None

    for target in [execution_plan.primary] + execution_plan.fallbacks:
        provider = target.provider
        try:
            if provider not in clients:
                clients[provider] = LLMClient(
                    provider, target.provider_config if target.provider_config else {}
                )
        except LLMError as e:
            last_error = e
            logger.exception(
                "Failed to initialize LLM client for provider '%s': %s", provider, e
            )
            continue

        for _ in range(execution_plan.retry.max_attempts):
            try:
                return await clients[provider].call_llm(
                    execution_plan.request,
                    target.model,
                    target.model_config,
                )
            except LLMError as e:
                last_error = e

                if _status_code_matches(execution_plan.retry.retry_on, e.status_code):
                    await asyncio.sleep(execution_plan.retry.backoff_sec)
                    continue

                # Not retryable (or no attempts left) on this target; try next fallback.
                break

    if last_error is not None:
        raise last_error

    raise LLMError(604, "No LLM targets could be executed")


# async def run_llm(
#     requests: AsyncIterable[LLMRequest],
#     llm_config: dict,
# ) -> AsyncIterator[LLMResponse]:
#     """
#     Lazily process LLM requests from an async iterable and yield results as they complete.
#     Each yielded item matches the LLMClient.call_llm return (function_call flag, text).
#     """

#     clients: dict[str, LLMClient] = {}
#     pending: set[asyncio.Task[LLMResponse]] = set()

#     async def handle(req: LLMRequest) -> LLMResponse:
#         provider = llm_config["models"][req.model]["provider"]
#         if provider not in clients:
#             clients[provider] = LLMClient(provider, llm_config["providers"][provider])
#         return await clients[provider].call_llm(req)

#     async for req in requests:
#         pending.add(asyncio.create_task(handle(req)))

#         if len(pending) >= max_concurrency:
#             done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
#             for task in done:
#                 pending.remove(task)
#                 try:
#                     response = task.result()
#                     yield response
#                 except Exception:
#                     # yield LLMResponse(request_id=req.request_id, error=str(e))
#                     pass

#     while pending:
#         done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
#         for task in done:
#             pending.remove(task)
#             try:
#                 response = task.result()
#                 yield response
#             except Exception:
#                 # yield LLMResponse(request_id="", error=str(e))
#                 pass

#     # TODO: retries
#     # TODO: max in-flight requests / backpressure
#     # TODO: optional per-request error handling strategy
