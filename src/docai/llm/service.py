from __future__ import annotations

import asyncio
from logging import getLogger

from docai.llm.client import LLMClient, create_client
from docai.llm.datatypes import LLMConfig, LLMModelConfig, LLMRequest
from docai.llm.errors import LLMError

logger = getLogger("docai_project")


class LLMService:
    def __init__(self, config: LLMConfig):
        self._connections: list[tuple[LLMClient, LLMModelConfig]] = []
        self._config: LLMConfig = config

        # set up cache
        self._cache = None
        raise NotImplementedError("Cache setup not implemented")

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

    async def _run(
        self, connection: tuple[LLMClient, LLMModelConfig], request: LLMRequest
    ):
        client, model_config = connection
        async with self._config.concurrency.concurrency_semaphore:
            await client.generate(request, model_config)

    async def _cache_or_run(self):
        # this gets connection details and Request. If they already exist, cache it.
        ...

    async def _generate(self, request: LLMRequest):

        for connection in self._connections:
            async with self._config.concurrency.concurrency_semaphore:
                pass

    async def generate_batch(self):
        # TODO: Implement batch generation logic
        ...

    async def generate_agent(self): ...

    async def generate_agent_batch(self): ...
