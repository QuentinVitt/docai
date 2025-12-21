import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from typing import Any

import yaml
from google import genai
from google.genai import types

logger = logging.getLogger("docai_project")

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "llm_config.yaml"


class LLMRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"


@dataclass
class LLMFunctionRequest:
    name: str
    args: dict[str, Any]


@dataclass
class LLMMessage:
    role: LLMRole
    content: str | LLMFunctionRequest


@dataclass
class LLMRequest:
    request_id: str
    model: str
    contents: list[LLMMessage]
    system_prompt: str | None = None
    agent_mode: bool = False
    structured_output: dict | None = None
    model_config: dict[str, Any] | None = None


@dataclass
class LLMResponse:
    request_id: str
    response: LLMMessage
    function_call: bool = False
    error: Any = None  # TODO: Implement and define proper error types and handle them in the LLMResponse


class LLMClient:
    def __init__(self, provider: str):
        logger.debug("Initializing llm_client for %s", provider)

        # load provider config:
        logger.debug("Loading provider config")
        try:
            llm_config_raw = resources.open_text(CONFIG_PACKAGE, CONFIG_FILE)
        except FileNotFoundError:
            logger.critical("Logging configuration file not found", exc_info=True)
            exit(1)

        provider_config = yaml.safe_load(llm_config_raw)["providers"][provider]

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
                model_config["system_prompt"] = request.system_prompt
            if request.structured_output:
                logger.critical("Structured output is implemented")
                exit(1)

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
            except Exception as e:
                logger.exception("Google LLM call failed: \n%s", e, exc_info=True)
                raise

            return LLMResponse(
                request_id=request.request_id,
                response=LLMMessage(
                    role=LLMRole.ASSISTANT,
                    content=response.text if response.text else "",
                ),
            )

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
