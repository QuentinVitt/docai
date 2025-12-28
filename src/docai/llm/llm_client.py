import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from google import genai
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
    args: dict[str, Any]


@dataclass
class LLMFunctionResponse:
    name: str
    result: Any


@dataclass
class LLMMessage:
    role: LLMRole
    content: str | LLMFunctionRequest | LLMFunctionResponse


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
    function_call: bool = False
    error: str | None = (
        None  # TODO: Implement and define proper error types and handle them in the LLMResponse
    )


class LLMClient:
    def __init__(self, provider: str, provider_config: dict):
        logger.debug("Initializing llm_client for %s", provider)

        match provider:
            case "google":
                logger.debug("Generating call_llm for google")
                self.call_llm = self.__configure_google_llm(provider_config)
            case _:
                logger.critical("Unsupported provider: %s", provider)
                exit(1)

    def __configure_google_llm(self, provider_config: dict):
        # check if API key is set
        logger.debug("Checking if an API key is set")
        if not provider_config["api_key_env"]:
            logger.critical("API key env is not specified in config file")
            exit(1)
        api_key_name = provider_config["api_key_env"]
        api_key = os.environ.get(api_key_name)
        if not api_key:
            logger.critical("API key %s not set", api_key_name)
            exit(1)

        try:
            client = genai.Client(api_key=api_key)
        except Exception:
            logger.critical("Failed to create Google client", exc_info=True)
            exit(1)

        logger.debug("New google client created")

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
                # Build tools list exactly as in Gemini examples:
                # tools = [types.Tool(function_declarations=[tool_1, tool_2, ...])]
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
            google_contents = [
                self.__google_content_from_dict(message) for message in request.contents
            ]

            def _call():
                return client.models.generate_content(
                    model=request.model,
                    contents=google_contents,
                    config=types.GenerateContentConfig(**model_config),
                )

            try:
                response = await asyncio.to_thread(_call)
                return LLMResponse(request_id=request.request_id, response=response)
            except Exception as e:
                logger.exception("Google LLM call failed", exc_info=True)
                return LLMResponse(request_id=request.request_id, error=str(e))

        return wrapper

    def __google_content_from_dict(self, message: LLMMessage) -> types.Content:
        """
        Translate an internal LLMMessage into a Google Content object.
        Ensures text parts are strings and handles function call payloads explicitly.
        """
        try:
            match message.role:
                case LLMRole.USER:
                    if not isinstance(message.content, str):
                        logger.critical(
                            "User content must be text, got %s",
                            type(message.content).__name__,
                            exc_info=True,
                        )
                        exit(1)
                    return types.Content(
                        role="user", parts=[types.Part(text=message.content)]
                    )
                case LLMRole.ASSISTANT:
                    if not isinstance(message.content, str):
                        logger.critical(
                            "Model content must be text, got %s",
                            type(message.content).__name__,
                            exc_info=True,
                        )
                        exit(1)
                    return types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=message.content)],
                    )
                case LLMRole.SYSTEM:
                    logger.critical(
                        "System content not supported for google llm", exc_info=True
                    )
                    exit(1)
                case LLMRole.FUNCTIONREQ:
                    if not isinstance(message.content, LLMFunctionRequest):
                        logger.critical(
                            "Model content must be LLMFunctionRequest, got %s",
                            type(message.content).__name__,
                            exc_info=True,
                        )
                        exit(1)

                    return types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name=message.content.name, args=message.content.args
                                )
                            )
                        ],
                    )

                case LLMRole.FUNCTIONRESP:
                    if not isinstance(message.content, LLMFunctionResponse):
                        logger.critical(
                            "Function response content must be LLMFunctionResponse, got %s",
                            type(message.content).__name__,
                            exc_info=True,
                        )
                        exit(1)

                    function_response_part = types.Part.from_function_response(
                        name=message.content.name,
                        response={"result": message.content.result},
                    )
                    return types.Content(role="user", parts=[function_response_part])

                case _:
                    logger.critical(
                        "Undefined role for llm_call: %s", message.role, exc_info=True
                    )
                    exit(1)

        except KeyError as e:
            logger.critical("Missing or wrong key in content: %s", e, exc_info=True)
            exit(1)
        except Exception:
            logger.exception(
                "Unidentfied error while translating content for google llm",
                exc_info=True,
            )
            exit(1)
