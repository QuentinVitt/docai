from dataclasses import dataclass
from enum import Enum
from typing import Any


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
    Base class for all LLM-related errors. 4xx and 5xx errors raise LLMClientError and LLMServerErrors.
    6xx errors are custom errors raised by the system.
    """

    def __init__(self, status_code: int, response: str = ""):
        self.status_code = status_code
        self.response = response
        super().__init__(f"code {self.status_code} -> {self.response}")


class LLMClientError(LLMError):
    """Raised when an error occurs while interacting with an LLMClient."""


class LLMServerError(LLMError):
    """Raised when an error occurs on the server side while interacting with an LLMClient."""
