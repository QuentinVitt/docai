import logging

from docai.llm.google_provider import configure_google_call_llm, configure_google_client
from docai.llm.models import (
    LLMClientError,
    LLMError,
    LLMRequest,
    LLMResponse,
    LLMServerError,
)

logger = logging.getLogger("docai_project")


class LLMClient:
    """Unified interface for interacting with different LLM providers."""

    def __init__(self, provider: str, provider_config: dict):
        logger.debug("Initializing LLMClient for provider '%s'", provider)

        match provider:
            case "google":
                self.client, self.cleanup = configure_google_client(provider_config)
                self.call_llm = configure_google_call_llm(self.client)
                logger.debug("Google LLM client and call wrapper configured")
            case _:
                logger.error("Provider '%s' is not supported", provider)
                raise LLMError(600, f"LLMClient not found for provider: {provider}")
