from __future__ import annotations

import asyncio
import uuid
from logging import getLogger
from typing import AsyncIterable, AsyncIterator, Awaitable, Callable, Optional

from docai.llm.cache import LLMCache
from docai.llm.client import LLMClient, create_client
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMConfig,
    LLMFunctionCall,
    LLMFunctionResponse,
    LLMMessage,
    LLMModelConfig,
    LLMProviderMessage,
    LLMRequest,
    LLMUserMessage,
)
from docai.llm.errors import LLMError
from docai.llm.runner import run

logger = getLogger(__name__)


class LLMService:
    def __init__(self, config: LLMConfig):
        self._connections: list[tuple[LLMClient, LLMModelConfig]] = []
        self._config: LLMConfig = config

        # set up cache
        self._cache = LLMCache(self._config.cache)

    @classmethod
    async def create(cls, config: LLMConfig) -> LLMService:
        """Creates and initializes an LLMService with clients for each profile."""
        service = cls(config)
        for profile in config.profiles:
            try:
                client = await create_client(profile.provider)
                service._connections.append((client, profile.model))
                logger.debug("Created client for provider %s", profile.provider.name)
            except LLMError as e:
                logger.error(
                    "Failed to create client for provider %s",
                    profile.provider.name,
                    exc_info=e,
                )

        if not service._connections:
            logger.error(
                "Failed to create LLMService because no clients could be created"
            )
            raise LLMError(608, "Failed to create LLMService")

        return service

    async def close(self):
        """Closes all client connections."""
        try:
            close_tasks = [client.close() for client, _ in self._connections]
            await asyncio.gather(*close_tasks)
            logger.debug("All LLM clients closed.")
        except Exception as e:
            logger.error("Failed to close LLM clients", exc_info=e)
            raise LLMError(609, "Failed to close LLM clients")

    async def _generate(
        self, client: LLMClient, model_config: LLMModelConfig, request: LLMRequest
    ) -> tuple[str | dict, LLMProviderMessage]:
        result = await run(
            self._cache,
            request,
            model_config,
            client,
            self._config.retry,
            self._config.concurrency.concurrency_semaphore,
        )
        if isinstance(result.response, LLMAssistantMessage):
            return result.response.content, result.response
        elif isinstance(result.response, LLMFunctionCall):
            return {
                "function_call": {
                    "name": result.response.name,
                    "arguments": result.response.arguments,
                }
            }, result.response

        raise LLMError(601, "Unsupported response type: " + str(type(result.response)))

    async def generate(
        self,
        prompt: str | LLMUserMessage | LLMRequest,
        system_prompt: Optional[str] = None,
        history: Optional[list[LLMMessage]] = None,
        structured_output: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ) -> tuple[str | dict, LLMProviderMessage]:

        if isinstance(prompt, LLMRequest):
            request = prompt
        else:
            request_args = {
                "prompt": prompt
                if isinstance(prompt, LLMUserMessage)
                else LLMUserMessage(content=prompt),
                "history": history if history else [],
            }
            if system_prompt:
                request_args["system_prompt"] = system_prompt
            if structured_output:
                request_args["structured_output"] = structured_output
            if id:
                request_args["id"] = id
            request = LLMRequest(**request_args)

        # go over all connections with request. return first hit
        for client, model_config in self._connections:
            try:
                return await self._generate(client, model_config, request)
            except Exception as e:
                logger.error(
                    f"Failed to generate request {request}with {client}, {model_config}",
                    exc_info=e,
                )

        raise LLMError(610, "Failed to generate response with all connections")

    async def generate_batch(
        self, requests: AsyncIterator[LLMRequest | dict]
    ) -> AsyncIterable[tuple[str | dict, LLMProviderMessage] | Exception]:
        inflight_sem = self._config.concurrency.inflight_requests
        pending: set[asyncio.Task] = set()

        def _release_inflight(_t: asyncio.Task) -> None:
            inflight_sem.release()

        try:
            async for req_data in requests:
                # 1. Backpressure on ingestion
                await inflight_sem.acquire()

                # 2. Parse request
                try:
                    req = (
                        LLMRequest(**req_data)
                        if isinstance(req_data, dict)
                        else req_data
                    )
                except Exception as e:
                    inflight_sem.release()
                    yield e
                    continue

                # 3. Create task and track it
                t = asyncio.create_task(self.generate(prompt=req))
                t.add_done_callback(_release_inflight)
                pending.add(t)

                # 4. Yield anything that happens to be done
                done = {x for x in pending if x.done()}
                if done:
                    pending -= done
                    for task in done:
                        try:
                            yield task.result()
                        except Exception as e:
                            yield e

            # 5. Flush remaining tasks after ingestion is complete
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
            # 6. Clean up if consumer breaks out of the loop early
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def generate_agent(
        self,
        prompt: str | LLMUserMessage | LLMRequest,
        tool_executor: Callable[[LLMFunctionCall], Awaitable[LLMFunctionResponse]],
        system_prompt: Optional[str] = None,
        history: Optional[list[LLMMessage]] = None,
        allowed_tools: Optional[set[str]] = None,
        structured_output: Optional[dict] = None,
        max_turns: int = 10,
        id: Optional[uuid.UUID] = None,
    ) -> tuple[str | dict, LLMProviderMessage]:

        # Build initial request (same as generate)
        if isinstance(prompt, LLMRequest):
            request = prompt
        else:
            request_args = {
                "prompt": LLMUserMessage(content=prompt)
                if isinstance(prompt, str)
                else prompt,
                "history": history if history else [],
            }
            if system_prompt:
                request_args["system_prompt"] = system_prompt
            if allowed_tools:
                request_args["allowed_tools"] = allowed_tools
            if structured_output:
                request_args["structured_output"] = structured_output
            if id:
                request_args["id"] = id
            request = LLMRequest(**request_args)

        # Agent loop: Reason → Act → Observe → repeat
        for turn in range(max_turns):
            # Try all connections, return on first success (same as generate)
            result = None
            for client, model_config in self._connections:
                try:
                    result = await run(
                        self._cache,
                        request,
                        model_config,
                        client,
                        self._config.retry,
                        self._config.concurrency.concurrency_semaphore,
                    )
                    break
                except Exception as e:
                    logger.error(
                        "Agent turn %d failed with %s, %s",
                        turn + 1,
                        client,
                        model_config,
                        exc_info=e,
                    )

            if result is None:
                raise LLMError(610, "Failed to generate response with all connections")

            # Reason: text response — agent is done
            if isinstance(result.response, LLMAssistantMessage):
                return result.response.content, result.response

            # Act + Observe: tool call — execute and continue
            if isinstance(result.response, LLMFunctionCall):
                logger.debug(
                    "Agent turn %d: calling tool '%s' for request %s",
                    turn + 1,
                    result.response.name,
                    request.id,
                )
                function_response = await tool_executor(result.response)

                # Grow history with this turn, make function response the new prompt
                request = LLMRequest(
                    prompt=function_response,
                    system_prompt=request.system_prompt,
                    history=list(request.history) + [request.prompt, result.response],
                    allowed_tools=request.allowed_tools,
                    structured_output=request.structured_output,
                    id=request.id,
                )
                continue

            raise LLMError(601, "Unsupported response type: " + str(type(result.response)))

        raise LLMError(612, f"Agent exceeded maximum turns ({max_turns})")
