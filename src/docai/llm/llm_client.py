import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from docai.llm.agent_tools import TOOL_REGISTRY
from docai.llm.google_provider import configure_google_call_llm, configure_google_client

logger = logging.getLogger("docai_project")


class LLMRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTIONREQ = "function_request"
    FUNCTIONRESP = "function_response"


@dataclass
class LLMFunctionRequest:
    name: str
    args: dict[str, Any] | None


@dataclass
class LLMFunctionResponse:
    name: str
    result: Any


@dataclass
class LLMMessage:
    role: LLMRole
    content: str | LLMFunctionRequest | LLMFunctionResponse
    original_content: Any = None


@dataclass
class LLMRequest:
    request_id: str
    model: str
    contents: list[LLMMessage]
    system_prompt: str | None = None
    agent_functions: list[str] | None = None
    structured_output: dict | None = None
    model_config: dict[str, Any] | None = None


@dataclass
class LLMResponse:
    request_id: str
    response: LLMMessage | None = None


class LLMError(Exception):
    """
    Base class for all LLM-related errors. 4xx and 5xx errors raise LLMClientError and LLMServerErrors. 6xx errors are custom errors raised by the system
    """

    # code 600: LLMClientNotFound - LLMClient is not a supported provider
    # code 601: Unexpected error
    # code 602: couldn't convert LLM content to provider content
    # code 603: faulty response from LLMCall received

    def __init__(self, status_code: int, response: str = ""):
        self.status_code = status_code
        self.response = response
        super().__init__(f"code {self.status_code} -> {self.response}")


class LLMClientError(LLMError):
    """Raised when an error occurs while interacting with an LLMClient."""

    # code 400: Bad Request
    # code 401: Authentication Error
    # code 403: Permission Denied
    # code 404: Not Found Error
    # code 408: Request Timeout
    # code 409: Confflict Error
    # code 422: Unprocessable Entity
    # code 429: Rate Limit Exceeded

    pass


class LLMServerError(LLMError):
    """Raised when an error occurs on the server side while interacting with an LLMClient."""

    # code 500:
    # code 501:
    # code 502:
    pass


class LLMClient:
    """Unified interface for interacting with different LLM providers."""

    def __init__(self, provider: str, provider_config: dict):
        logger.debug("Initializing LLMClient for provider '%s'", provider)

        match provider:
            case "google":
                self.client, self.cleanup = configure_google_client(provider_config)
                self.call_llm = configure_google_call_llm()
                logger.debug("Google LLM client and call wrapper configured")
            case _:
                logger.error("Provider '%s' is not supported", provider)
                raise LLMError(600, f"LLMClient not found for provider: {provider}")
