from __future__ import annotations

import asyncio
import uuid
from logging import getLogger
from typing import Optional

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
    LLMResponse,
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
        prompt: str | LLMUserMessage,
        system_prompt: Optional[str] = None,
        history: Optional[list[LLMMessage]] = None,
        structured_output: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
    ) -> tuple[str | dict, LLMProviderMessage]:

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

    async def generate_batch(self): ...

    async def generate_agent(self): ...

    async def generate_agent_batch(self): ...
