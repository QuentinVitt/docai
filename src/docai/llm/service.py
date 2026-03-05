from __future__ import annotations

import asyncio
import uuid
from logging import getLogger
from typing import AsyncIterable, AsyncIterator, Optional

from docai.llm.cache import LLMCache
from docai.llm.client import LLMClient, create_client
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMConfig,
    LLMFunctionCall,
    LLMMessage,
    LLMModelConfig,
    LLMProviderMessage,
    LLMRequest,
    LLMUserMessage,
)
from docai.llm.errors import LLMError
from docai.llm.runner import run

logger = getLogger("docai_project")


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

    # async def generate_agent(
    #     self,
    #     prompt: str | LLMUserMessage | LLMRequest,
    #     system_prompt: Optional[str] = None,
    #     history: Optional[list[LLMMessage]] = None,
    #     structured_output: Optional[dict] = None,
    #     allowed_tools: Optional[set[str]] = None,
    #     id: Optional[uuid.UUID] = None,
    # ) -> tuple[str | dict, LLMProviderMessage]:
    #     # build initial request
    #     if isinstance(prompt, LLMRequest):
    #         request = prompt
    #     else:
    #         if not history:
    #             history = []
    #         request_dict = {
    #             "prompt": LLMUserMessage(prompt) if isinstance(prompt, str) else prompt,
    #             "system_prompt": system_prompt,
    #             "history": history
    #         }
    #         if structured_output:
    #             request_dict["structured_output"] = structured_output
    #         if allowed_tools:
    #             request_dict["allowed_tools"] = allowed_tools
    #         request = LLMRequest(**request_dict)

    #     # agent loop:
    #     while True:
    #         # Resason
    #         # Act
    #         # observe
    #         # repeat

    # async def generate_agent_batch(self): ...
