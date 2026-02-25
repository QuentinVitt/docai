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
class LLMConcurrencyConfig:
    max_concurrency: int
    concurrency_semaphore: Semaphore
    inflight_requests: Semaphore


@dataclass(frozen=True)
class LLMRetryConfig:
    max_retries: int
    retry_delay: int
    retry_on: list[str] = field(default_factory=lambda: ["5..", "408", "429"])


class LLMCacheModelConfigStrategy(Enum):
    NEWEST = "newest"
    BEST_MATCH = "best_match"
    EXACT_MATCH = "exact_match"


@dataclass(frozen=True)
class LLMCacheConfig:
    use_cache: bool
    cache_dir: str
    max_disk_size: int = (
        1_000_000_000  # space in bytes occupied by cache - deletes oldest entries first
    )
    max_lru_size: int = 1_000  # max number of entries in the lru cache
    max_age: int = 86_400  # max age of disk cache usable in seconds
    clean_old_entries: bool = False  # clean old entries from disk cache
    model_config_strategy: LLMCacheModelConfigStrategy = LLMCacheModelConfigStrategy.EXACT_MATCH  # don't need to match model config and can return newest, or best match or something else


@dataclass(frozen=True)
class LLMConfig:
    profiles: list[LLMProfileConfig]
    concurrency: LLMConcurrencyConfig
    retry: LLMRetryConfig
    cache: LLMCacheConfig
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

    def __str__(self):
        return f"User: {self.content}"


@dataclass(frozen=True)
class LLMAssistantMessage(LLMProviderMessage):
    content: str

    def __str__(self):
        return f"Assistant: {self.content}"


@dataclass(frozen=True)
class LLMFunctionCall(LLMProviderMessage):
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __str__(self):
        return f"Function Call: {self.name}({', '.join(f'{k}={v}' for k, v in self.arguments.items())})"


@dataclass(frozen=True)
class LLMFunctionResponse(LLMInternalMessage):
    call: LLMFunctionCall
    response: dict[str, Any] = field(default_factory=dict)

    def __str__(self):
        return f"Function Response: {self.call.name}({', '.join(f'{k}={v}' for k, v in self.call.arguments.items())}) -> {self.response}"


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
