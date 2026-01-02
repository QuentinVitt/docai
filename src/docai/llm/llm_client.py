import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from docai.llm.agent_tools import TOOL_REGISTRY

logger = logging.getLogger("docai_project")

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "llm_config.yaml"


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
    """LLMClient is a class that provides an unified interface for interacting with different LLM providers.
    Returns an instance of LLMClient or raises LLMClientNotFound if the provider is not supported.
    """

    def __init__(self, provider: str, provider_config: dict):
        logger.debug("Initializing llm_client for %s", provider)

        match provider:
            case "google":
                logger.debug("Generating call_llm for google")
                self.client, self.cleanup = self.__configure_google_client(
                    provider_config
                )
                self.call_llm = self.__configure_google_call_llm()
            case _:
                raise LLMError(600, f"LLMClient not found for provider: {provider}")

    def __configure_google_client(self, provider_config: dict):
        api_key_name = (
            provider_config["api_key_env"]
            if provider_config["api_key_env"]
            else "GEMINI_API_KEY"
        )
        api_key = os.environ.get(api_key_name)
        if not api_key:
            raise ValueError(f"API key {api_key_name} not set")
        try:
            client = genai.Client(
                api_key=api_key, http_options=types.HttpOptions(async_client_args={})
            ).aio

            async def cleanup():
                await client.aclose()

            return client, cleanup

        except genai_errors.APIError as e:
            if 400 <= e.code < 500:
                raise LLMClientError(e.code, e.message if e.message else "")
            elif 500 <= e.code < 600:
                raise LLMServerError(e.code, e.message if e.message else "")

            raise LLMError(
                e.code,
                e.message if e.message else "",
            )

        except Exception as e:
            raise LLMError(601, f"Unexpected error: {e}")

    def __configure_google_call_llm(self):
        async def wrapper(request: LLMRequest) -> LLMResponse:
            # Keep wrapper async; offload sync SDK call to a thread
            # Copy so we don't mutate caller-provided config
            model_config = dict(request.model_config) if request.model_config else {}
            if request.system_prompt:
                model_config["system_instruction"] = request.system_prompt
            if request.structured_output:
                model_config["response_mime_type"] = "application/json"
                model_config["response_json_schema"] = request.structured_output
            if request.agent_functions:
                function_decls = [
                    TOOL_REGISTRY[name]
                    for name in request.agent_functions
                    if name in TOOL_REGISTRY
                ]
                if function_decls:
                    model_config["tools"] = [
                        types.Tool(function_declarations=function_decls)
                    ]

            # setup the content:
            try:
                google_contents = [
                    self.__google_content_from_dict(message)
                    for message in request.contents
                ]
            except ValueError as e:
                raise LLMError(602, str(e))
            except Exception as e:
                raise LLMError(601, str(e))

            try:
                response = await self.client.models.generate_content(
                    model=request.model,
                    contents=google_contents,
                    config=types.GenerateContentConfig(**model_config),
                )
            except genai_errors.APIError as e:
                if 400 <= e.code < 500:
                    raise LLMClientError(e.code, e.message if e.message else "")
                if 500 <= e.code < 600:
                    raise LLMServerError(e.code, e.message if e.message else "")
                raise LLMError(e.code, e.message if e.message else "")

            except Exception as e:
                raise LLMError(601, str(e))

            # Check if there is a response:
            if not (
                response
                and response.candidates
                and response.candidates[0]
                and response.candidates[0].content
                and response.candidates[0].content.parts
                and response.candidates[0].content.parts[0]
            ):
                raise LLMError(
                    603,
                    "response didn't contain content or had faulty content.\nResponse: "
                    + str(response),
                )
                # Check If there was a function call (can only happen if it is in agent mode)
            if (
                request.agent_functions
                and response.candidates[0].content.parts[0].function_call
            ):
                if not response.candidates[0].content.parts[0].function_call.name:
                    raise LLMError(
                        603,
                        "response specified a function call without a name.\nResponse: "
                        + str(response),
                    )

                content = LLMFunctionRequest(
                    name=response.candidates[0].content.parts[0].function_call.name,
                    args=response.candidates[0].content.parts[0].function_call.args,
                )

                return LLMResponse(
                    request_id=request.request_id,
                    response=LLMMessage(
                        role=LLMRole.FUNCTIONREQ,
                        content=content,
                        original_content=response.candidates[0].content,
                    ),
                )

            # Check if there was a normal response:
            if response.text:
                return LLMResponse(
                    request_id=request.request_id,
                    response=LLMMessage(
                        role=LLMRole.ASSISTANT,
                        content=response.text,
                        original_content=response.candidates[0].content,
                    ),
                )

            raise LLMError(
                602, "response didn't contain any content.\nResponse: " + str(response)
            )

        return wrapper

    def __google_content_from_dict(self, message: LLMMessage) -> types.Content:
        """
        Translate an internal LLMMessage into a Google Content object.
        Ensures text parts are strings and handles function call payloads explicitly.
        """

        match message.role:
            case LLMRole.USER:
                if not isinstance(message.content, str):
                    raise ValueError(
                        f"User content must be text, got {type(message.content).__name__}"
                    )

                return types.UserContent(
                    parts=[types.Part.from_text(text=message.content)]
                )

            case LLMRole.ASSISTANT:
                if message.original_content is not None:
                    return message.original_content

                if not isinstance(message.content, str):
                    raise ValueError(
                        f"Assistant content must be text, got {type(message.content).__name__}"
                    )

                return types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=message.content)],
                )

            case LLMRole.SYSTEM:
                raise ValueError("System content not supported for google llm")

            case LLMRole.FUNCTIONREQ:
                if message.original_content is not None:
                    return message.original_content

                if not isinstance(message.content, LLMFunctionRequest):
                    raise ValueError(
                        f"Function request content must be LLMFunctionRequest, got {type(message.content).__name__}"
                    )

                return types.ModelContent(
                    parts=[
                        types.Part.from_function_call(
                            name=message.content.name,
                            args=message.content.args if message.content.args else {},
                        )
                    ]
                )

            case LLMRole.FUNCTIONRESP:
                if not isinstance(message.content, LLMFunctionResponse):
                    raise ValueError(
                        f"Function response content must be LLMFunctionResponse, got {type(message.content).__name__}"
                    )

                function_response_part = types.Part.from_function_response(
                    name=message.content.name,
                    response={"result": message.content.result},
                )
                return types.Content(role="user", parts=[function_response_part])

            case _:
                raise ValueError(f"Undefined role for content: {message.role}")
