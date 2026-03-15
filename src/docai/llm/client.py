from __future__ import annotations

from logging import getLogger
from typing import Optional, Protocol

from docai.config.datatypes import LLMModelConfig, LLMProviderConfig
from docai.llm.datatypes import LLMRequest, LLMResponse
from docai.llm.errors import LLMError
from docai.llm.google_provider import GoogleClient

logger = getLogger(__name__)


class LLMClient(Protocol):
    """Unified interface for interacting with different LLM providers."""

    @classmethod
    async def create(
        cls, config: LLMProviderConfig, custom_tools: Optional[dict[str, dict]] = None
    ) -> LLMClient: ...

    async def generate(
        self, request: LLMRequest, config: LLMModelConfig
    ) -> LLMResponse: ...

    async def close(self) -> None: ...


async def create_client(
    config: LLMProviderConfig, tools: Optional[dict[str, dict]] = None
) -> LLMClient:

    match config.name:
        case "google":
            return await GoogleClient.create(config, tools)
        case _:
            logger.error("Provider '%s' is not supported", config.name)
            raise LLMError(
                600,
                f"Provider in LLMClient initialization not found: {config.name}",
            )
