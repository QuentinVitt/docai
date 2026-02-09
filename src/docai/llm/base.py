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
    LLMRequest,
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


@dataclass
class ChatRequest:
    id: str
    prompt: str
    system_prompt: str | None = None
    structured_output: Optional[dict[str, Any]] = None
    agent: bool = False
    history: Optional[list[LLMMessage | str]] = None


@dataclass
class ChatResponse:
    id: str
    response: str | dict[str, Any]
    message: LLMMessage


async def run_chat(chat_request: ChatRequest, config: Config) -> ChatResponse:
    try:
        semaphore = config.llm_args["semaphore"]
    except KeyError:
        raise LLMError(status_code=605, response="Semaphores not configured")

    async with semaphore:
        # 1. Build Request
        # 2. Check if Request is cached
        # 3. If cached: return
        # 4. else call LLM and return and cache answer.
        # We also sometimes need to run an agent.
        pass
    raise NotImplementedError("Implement this function")


# how do we want to call this function, we need a plural and singular
# 1. chat | chats
# 2. run_llm | run_llms
# 3. run_chat | run chats
# 4. call_llm | call_llms
# 5. or same name with different inputs. If chat_requests is a list, we do this extra stuff, else we just do _chat


async def chat(
    chat_requests: AsyncIterator[ChatRequest], config: Config
) -> AsyncIterable[ChatResponse | Exception]:
    try:
        inflight_sem: asyncio.Semaphore = config.llm_args["inflight_semaphore"]
    except KeyError:
        raise LLMError(status_code=605, response="Semaphores not configured")

    pending: set[asyncio.Task[ChatResponse]] = set()

    def _release_inflight(_t: asyncio.Task) -> None:
        inflight_sem.release()

    try:
        async for req in chat_requests:
            # Global backpressure across ALL chat() calls:
            await inflight_sem.acquire()

            t = asyncio.create_task(run_chat(req, config))
            t.add_done_callback(_release_inflight)
            pending.add(t)

            # Optional: yield any tasks that are already done (cheap)
            done = {x for x in pending if x.done()}
            if done:
                pending -= done
                for task in done:
                    try:
                        yield task.result()
                    except Exception as e:
                        yield e

        # Flush remaining tasks
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    yield task.result()
                except Exception as e:
                    yield e

    finally:
        # If the generator is cancelled / consumer stops early, don't leak tasks
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def _build_request(chat_request: ChatRequest, config: Config) -> LLMExecutionPlan:
    message = LLMMessage(role=LLMRole.USER, content=chat_request.prompt)
    contents = [message]
    if chat_request.history:
        contents += [
            LLMMessage(role=LLMRole.USER, content=cnt) if isinstance(cnt, str) else cnt
            for cnt in chat_request.history
        ]

    llm_default_profile_name = (
        config.cli_args.llm_default if config.cli_args.llm_default else "default"
    )
    llm_fallback_profile_name = (
        config.cli_args.llm_fallback if config.cli_args.llm_fallback else "fallback"
    )

    try:
        llm_default_profile = config.llm_args["profiles"][llm_default_profile_name]
    except KeyError as e:
        raise ValueError(f"LLM profile '{llm_default_profile_name}' not found") from e

    try:
        llm_fallback_profile = config.llm_args["profiles"][llm_fallback_profile_name]
    except KeyError as e:
        raise ValueError(f"LLM profile '{llm_fallback_profile_name}' not found") from e

    agent_tools = (
        config.llm_args.get("tools", {}).get("allowed", None)
        if chat_request.agent
        else None
    )

    request = LLMRequest(
        request_id=chat_request.id,
        contents=contents,
        system_prompt=chat_request.system_prompt,
        agent_functions=agent_tools,
    )
    raise NotImplementedError("Implement _build_request")
