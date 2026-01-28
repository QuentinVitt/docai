from dataclasses import dataclass, field
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
    original_content: tuple[str, Any] | None = None


@dataclass
class LLMRequest:
    request_id: str
    contents: list[LLMMessage]
    system_prompt: str | None = None
    agent_functions: list[str] | None = None
    structured_output: dict | None = None


@dataclass
class LLMResponse:
    request_id: str
    response: LLMMessage | None = None


@dataclass
class LLMTarget:
    provider: str
    model: str
    model_config: dict[str, Any] | None = None
    provider_config: dict[str, Any] | None = None


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    retry_on: list[str] = field(
        default_factory=lambda: ["5..", "408", "429"]
    )  # Server errors. Write regex code to match error code
    backoff_sec: float = 2


@dataclass
class LLMExecutionPlan:
    request: LLMRequest
    primary: LLMTarget
    fallbacks: list[LLMTarget] = field(default_factory=list)
    retry: RetryPolicy = field(default_factory=RetryPolicy)


class LLMError(Exception):
    """
    Base class for all LLM-related errors. 4xx and 5xx errors raise LLMClientError and LLMServerErrors.
    6xx errors are custom errors raised by the system.
    """

    # code 600: LLMClientNotFound - LLMClient is not a supported provider
    # code 601: Unexpected error
    # code 602: couldn't convert LLM content to provider content
    # code 603: faulty response from LLMCall received
    # code 604: faulty LLMExecutionPlan - No LLMTarget specified
    # code 605: Error for configuring the semaphore for concurrent requests

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


class LLMServerError(LLMError):
    """Raised when an error occurs on the server side while interacting with an LLMClient."""

    # code 500:
    # code 501:
    # code 502:
