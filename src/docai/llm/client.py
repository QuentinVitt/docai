from logging import getLogger
from typing import Protocol

# from docai.llm.google_provider
from docai.llm.datatypes import (
    LLMModelConfig,
    LLMProviderConfig,
    LLMRequest,
    LLMResponse,
)
from docai.llm.errors import LLMError
from docai.llm.google_provider import GoogleClient

logger = getLogger("docai_project")


class LLMClient(Protocol):
    """Unified interface for interacting with different LLM providers."""

    async def generate(
        self, request: LLMRequest, config: LLMModelConfig
    ) -> LLMResponse: ...
    async def close(self) -> None: ...


def get_client(config: LLMProviderConfig) -> LLMClient:
    match config.name:
        case "google":
            return GoogleClient(config)
        case _:
            logger.error("Provider '%s' is not supported", config.name)
            raise LLMError(
                600,
                f"Provider in LLMClient initialization not found: {config.name}",
            )
