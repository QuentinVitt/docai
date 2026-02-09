import uuid
from abc import ABC
from asyncio import Semaphore
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

"""
Section for Config Dataclasses
"""


@dataclass(frozen=True)
class LLMModelConfig:
    name: str
    generation: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    api_key: str


@dataclass(frozen=True)
class LLMProfileConfig:
    provider: LLMProviderConfig
    model: LLMModelConfig


@dataclass(frozen=True)
class LLMProfileSelection:
    default: LLMProfileConfig
    fallback: LLMProfileConfig


@dataclass(frozen=True)
class LLMConcurrencyConfig:
    max_concurrency: int
    concurrent: Semaphore
    inflight_requests: Semaphore


@dataclass(frozen=True)
class LLMRetryConfig:
    max_retries: int
    retry_delay: int
    retry_on: list[str] = field(default_factory=lambda: ["5..", "408", "429"])


@dataclass(frozen=True)
class LLMConfig:
    profiles: LLMProfileSelection
    concurrency: LLMConcurrencyConfig
    retry: LLMRetryConfig
    tools: Optional[dict[str, Any]] = None


"""
Section for Request Dataclasses
"""


class LLMRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION_REQUEST = "function_request"
    FUNCTION_RESPONSE = "function_response"


@dataclass(frozen=True)
class LLMOriginalContent:
    provider: str
    content: Any


@dataclass(frozen=True)
class LLMMessage(ABC):
    """Base type for all messages"""

    pass


@dataclass(frozen=True)
class LLMInternalMessage(LLMMessage, ABC):
    """Messages created locally by the application"""

    pass


@dataclass(frozen=True)
class LLMProviderMessage(LLMMessage, ABC):
    """Messages originating from an LLM provider"""

    original_content: LLMOriginalContent


@dataclass(frozen=True)
class LLMUserMessage(LLMInternalMessage):
    content: str


@dataclass(frozen=True)
class LLMAssistantMessage(LLMProviderMessage):
    content: str


@dataclass(frozen=True)
class LLMFunctionCall(LLMProviderMessage):
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMFunctionResponse(LLMInternalMessage):
    call: LLMFunctionCall
    response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRequest:
    prompt: LLMInternalMessage
    system_prompt: Optional[str] = None
    history: list[LLMMessage] = field(default_factory=list)
    allowed_tools: Optional[set[str]] = (
        None  # holds a registry of function descriptions that are allowed to be called. If None: no function calls allowed
    )
    structured_output: Optional[dict] = (
        None  # holds a registry of functions that are allowed to be called if empty: no function calls allowed
    )
    id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class LLMResponse:
    response: LLMProviderMessage
    id: uuid.UUID
