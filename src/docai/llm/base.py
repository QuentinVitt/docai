import asyncio
import logging
import re
import uuid
from ast import Not
from dataclasses import dataclass
from typing import Any, AsyncIterable, AsyncIterator, Optional

from docai.config.loader import Config
from docai.llm.llm_client import LLMClient
from docai.llm.llm_datatypes import (
    LLMError,
    LLMExecutionPlan,
    LLMMessage,
    LLMResponse,
    LLMRole,
)

logger = logging.getLogger("docai_project")


def _status_code_matches(patterns: list[str], status_code: int) -> bool:
    for pattern in patterns:
        if re.fullmatch(pattern.replace("x", "\\d"), str(status_code)):
            return True
    return False


async def run_request(
    request: LLMExecutionPlan, clients: dict[str, LLMClient]
) -> LLMResponse:
    last_error: Optional[LLMError] = None

    for target in [request.primary] + request.fallbacks:
        provider = target.provider
        try:
            if provider not in clients:
                clients[provider] = LLMClient(
                    provider, target.provider_config if target.provider_config else {}
                )
        except LLMError as e:
            last_error = e
            continue

        for _ in range(request.retry.max_attempts):
            try:
                return await clients[provider].call_llm(
                    request.request,
                    target.model,
                    target.model_config,
                )
            except LLMError as e:
                last_error = e

                if _status_code_matches(request.retry.retry_on, e.status_code):
                    await asyncio.sleep(request.retry.backoff_sec)
                    continue

                # Not retryable (or no attempts left) on this target; try next fallback.
                break

    if last_error is not None:
        raise last_error

    raise LLMError(604, "No LLM targets could be executed")


# Behavior from outside
#
# Input is just a prompt & system prompt & config & structured output
# -> for multiple requests: we need an async generator. Maybe put that into a datatype.
# -> Datatype almost equal to LLMRequest
# -> do we want to allow agentic behaviour? methods can be used. For normal chat: YES so we can use this function again for the agent. For agent request: YES (always YES)


@dataclass
class ChatRequest:
    prompt: str
    system_prompt: str | None = None
    structured_output: Optional[dict[str, Any]] = None
    agent: bool = False
    history: Optional[list[LLMMessage | str]] = None


@dataclass
class ChatResponse:
    response: str | dict[str, Any]
    message: LLMMessage


async def run_chat(chat_request: ChatRequest, config: Config) -> ChatResponse:
    # use async with semaphore
    raise NotImplementedError("Implement this function")


async def chat(
    chat_requests: AsyncIterator[ChatRequest], config: Config
) -> AsyncIterable[ChatResponse | Exception]:
    try:
        semaphore = config.llm_args["semaphore"]
        max_inflight = config.llm_args["max_inflight"]
    except KeyError:
        raise LLMError(status_code=605, response="Semaphores not configured")

    pending: set[asyncio.Task[ChatResponse]] = set()

    try:
        async for chat_request in chat_requests:
            task = asyncio.create_task(run_chat(chat_request, config))
            pending.add(task)

            if semaphore.locked():
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                for t in done:
                    try:
                        yield t.result()
                    except Exception as e:
                        yield e

        # flush remaining
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )

            for t in done:
                try:
                    yield t.result()
                except Exception as e:
                    yield e

    finally:
        # If chat() exits early (cancel, error, consumer stops), don't leak tasks
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
