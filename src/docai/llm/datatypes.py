import uuid
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


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
class LLMSystemMessage(LLMInternalMessage):
    """Internal system feedback (validation errors, etc.) sent back to the model."""

    content: str

    def __str__(self):
        return f"System: {self.content}"


@dataclass(frozen=True)
class LLMAssistantMessage(LLMProviderMessage):
    content: str | dict

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
class LLMFunctionCallBatch(LLMProviderMessage):
    """Multiple parallel function calls from a single model turn."""

    calls: list[LLMFunctionCall]

    def __str__(self):
        return f"Function Call Batch: [{', '.join(c.name for c in self.calls)}]"


@dataclass(frozen=True)
class LLMFunctionResponseBatch(LLMInternalMessage):
    """Responses to a batch of parallel function calls, sent as a single user turn."""

    responses: list[LLMFunctionResponse]

    def __str__(self):
        return f"Function Response Batch: [{', '.join(r.call.name for r in self.responses)}]"


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
    response_validator: Optional[Callable[[str | dict], str | None]] = field(
        default=None, compare=False
    )


@dataclass(frozen=True)
class LLMResponse:
    response: LLMProviderMessage
    id: uuid.UUID
