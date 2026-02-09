import logging
from typing import Any, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMFunctionCall,
    LLMFunctionResponse,
    LLMMessage,
    LLMModelConfig,
    LLMOriginalContent,
    LLMProviderConfig,
    LLMProviderMessage,
    LLMRequest,
    LLMResponse,
    LLMUserMessage,
)
from docai.llm.errors import LLMClientError, LLMError, LLMServerError

logger = logging.getLogger("docai_project")


class GoogleClient:
    def __init__(
        self, config: LLMProviderConfig, custom_tools: Optional[dict[str, Any]] = None
    ):

        try:
            self._client = genai.Client(
                api_key=config.api_key,
                http_options=types.HttpOptions(async_client_args={}),
            ).aio
        except genai_errors.APIError as e:
            if 400 <= e.code < 500:
                raise LLMClientError(e.code, e.message)
            elif 500 <= e.code < 600:
                raise LLMServerError(e.code, e.message)
            else:
                raise LLMError(e.code, e.message)

        self._closed = False

        custom_tools = custom_tools or {}
        self._custom_tools = {}
        for name, description in custom_tools.items():
            self._custom_tools[name] = types.FunctionDeclaration(**description)

        self._provider_tools = {
            "search": types.Tool(google_search=types.GoogleSearch())
        }

        logger.debug("LLMClient for provider Google initialized")

    async def close(self) -> None:
        if self._closed:
            logger.debug("Google client already closed")
            return
        await self._client.aclose()
        self._closed = True
        logger.debug("Google client closed")

    async def generate(
        self, request: LLMRequest, config: LLMModelConfig
    ) -> LLMResponse:
        generation = dict(config.generation) if config.generation is not None else {}

        # configure system prompt
        if request.system_prompt is not None:
            generation["system_instruction"] = request.system_prompt
            logger.debug("System instruction set for request: %s", request.id)

        # configure structured output
        if request.structured_output is not None:
            generation["response_mime_type"] = "application/json"
            generation["response_json_schema"] = request.structured_output
            logger.debug("System instruction set for request %s", request.id)

        # configure tools
        tools = []
        funcs = []

        for tool in request.allowed_tools:
            if tool in self._custom_tools:
                funcs.append(self._custom_tools[tool])
            elif tool in self._provider_tools:
                tools.append(self._provider_tools[tool])
            else:
                logger.error(
                    "Tool '%s' from allowed_tools not found in for request %s",
                    tool,
                    request.id,
                )
                raise LLMError(606, f"Tool '{tool}' not found")

        if funcs:
            tools.append(types.Tool(function_declarations=funcs))

        if tools:
            generation["tools"] = tools
            logger.debug("Tools set for request %s", request.id)

        # configure content
        try:
            content = [_transform_content(request.prompt)]
            content += [_transform_content(message) for message in request.history]
            logger.debug(
                "Content transformed into provider specific format for request %s",
                request.id,
            )
        except genai.APIError as e:
            raise LLMError(607, f"Failed to transform content: {e}")

        try:
            response = await self._client.models.generate_content(
                model="something",
                content=["dummylist"],
                config=generation,
            )
        except genai_errors.APIError as e:
            if 400 <= e.code < 500:
                logger.error(
                    "Google API client error for request %s (code %s): %s",
                    request.request_id,
                    e.code,
                    str(e),
                )
                raise LLMClientError(e.code, e.message if e.message else "")
            if 500 <= e.code < 600:
                logger.error(
                    "Google API server error for request %s (code %s): %s",
                    request.request_id,
                    e.code,
                    str(e),
                )
                raise LLMServerError(e.code, e.message if e.message else "")
            raise LLMError(e.code, e.message if e.message else "")

        except Exception as e:
            logger.exception(
                "Unexpected error during Google call for request %s: %s",
                request.request_id,
                str(e),
            )
            raise LLMError(601, str(e))

        # check if there is a content:
        if not response.candidates[0].content:
            logger.error("No content returned from Google API")
            raise LLMError(602, "No content returned from Google API")

        # check if there was a function call:
        if response.function_call and len(response.function_call) > 1:
            raise LLMError(603, "Multiple function calls returned from Google API")
        elif response.function_call:
            return LLMResponse(
                response=LLMFunctionCall(
                    name=response.function_call.name,
                    arguments=response.function_call.arguments,
                    original_content=LLMOriginalContent(
                        provider="google", content=response.candidates[0].content
                    ),
                ),
                id=request.id,
            )

        # if there was no function call check if there was a normal response:
        if response.text:
            return LLMResponse(
                response=LLMAssistantMessage(
                    content=response.text,
                    original_content=LLMOriginalContent(
                        provider="google", content=response.candidates[0].content
                    ),
                ),
                id=request.id,
            )

        logger.error(
            "Response for request %s did not contain any text content: %s",
            request.request_id,
            str(response),
        )
        raise LLMError(
            602, "response didn't contain any content.\nResponse: " + str(response)
        )


def _transform_content(content: LLMMessage) -> types.Content:
    """
    Translate an internal LLMMessage into a Google Content object.
    Ensures text parts are strings and handles function call payloads explicitly.
    """

    # check if we can just return the original content:
    if (
        isinstance(content, LLMProviderMessage)
        and content.original_content.provider == "google"
    ):
        return content.original_content.content

    match content:
        case LLMUserMessage(content=c):
            return types.UserContent(parts=[types.Part.from_text(text=c)])

        case LLMAssistantMessage(content=c):
            return types.Content(
                role="model",
                parts=[types.Part.from_text(text=c)],
            )

        case LLMFunctionCall(name=fnc_name, arguments=fnc_args):
            return types.ModelContent(
                parts=[
                    types.Part.from_function_call(
                        name=fnc_name,
                        args=fnc_args,
                    )
                ]
            )

        case LLMFunctionResponse(call=call, response=response):
            function_response_part = types.Part.from_function_response(
                name=call.name,
                response=response,
            )
            return types.Content(role="user", parts=[function_response_part])

        case _:
            raise TypeError(
                f"Unsupported message type for Google transform: {type(content).__name__}"
            )
