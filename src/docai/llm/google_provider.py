from __future__ import annotations

import json
import logging
from typing import Any, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from docai.config.datatypes import LLMModelConfig, LLMProviderConfig
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMFunctionCall,
    LLMFunctionCallBatch,
    LLMFunctionResponse,
    LLMFunctionResponseBatch,
    LLMMessage,
    LLMOriginalContent,
    LLMProviderMessage,
    LLMRequest,
    LLMResponse,
    LLMSystemMessage,
    LLMUserMessage,
)
from docai.llm.errors import LLMClientError, LLMError, LLMServerError

logger = logging.getLogger(__name__)


class GoogleClient:
    def __init__(
        self, config: LLMProviderConfig, custom_tools: Optional[dict[str, dict]] = None
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
        for name, info in custom_tools.items():
            self._custom_tools[name] = types.FunctionDeclaration(**info["schema"])

        self._provider_tools: dict[str, types.Tool] = {}
        # Example: self._provider_tools["search"] = types.Tool(google_search=types.GoogleSearch())

    async def _validate(self) -> None:
        """
        Performs a lightweight API call to validate the provided credentials.

        Raises:
            LLMClientError: If the credentials are bad (4xx error).
            LLMServerError: If the backend has an issue (5xx error).
            LLMError: For other network or API-related errors.
        """
        try:
            # Get the async iterator for models and try to pull the first item.
            # This is a lightweight way to validate credentials and connectivity.
            await self._client.models.list()
        except genai_errors.APIError as e:
            if 400 <= e.code < 500:
                raise LLMClientError(e.code, e.message)
            elif 500 <= e.code < 600:
                raise LLMServerError(e.code, e.message)
            else:
                raise LLMError(e.code, e.message)
        except Exception as e:
            raise LLMError(601, str(e))

    @classmethod
    async def create(
        cls, config: LLMProviderConfig, custom_tools: Optional[dict[str, Any]] = None
    ) -> GoogleClient:
        """Creates and validates a new GoogleClient instance."""
        client = cls(config, custom_tools)
        await client._validate()
        return client

    async def close(self) -> None:
        if self._closed:
            return
        await self._client.aclose()
        self._closed = True

    async def generate(
        self, request: LLMRequest, config: LLMModelConfig
    ) -> LLMResponse:
        generation = dict(config.generation) if config.generation is not None else {}

        # configure system prompt
        if request.system_prompt is not None:
            generation["system_instruction"] = request.system_prompt

        # configure structured output (incompatible with function calling in Google API)
        if request.structured_output is not None and not request.allowed_tools:
            generation["response_mime_type"] = "application/json"
            generation["response_json_schema"] = request.structured_output

        # configure tools
        if request.allowed_tools:
            tools = []
            funcs = []

            for tool in request.allowed_tools:
                if tool in self._custom_tools:
                    funcs.append(self._custom_tools[tool])
                elif tool in self._provider_tools:
                    tools.append(self._provider_tools[tool])
                else:
                    raise LLMError(606, f"Tool '{tool}' not found")

            if funcs:
                tools.append(types.Tool(function_declarations=funcs))

            if tools:
                generation["tools"] = tools

        # configure content
        try:
            content = [_transform_content(message) for message in request.history]
            content.append(_transform_content(request.prompt))
        except genai_errors.APIError as e:
            raise LLMError(607, f"Failed to transform content: {e}")

        # Inject schema into user message when tools+structured_output are both set
        # (Google API doesn't support response_mime_type + function calling simultaneously)
        if (
            request.allowed_tools
            and request.structured_output is not None
            and isinstance(request.prompt, LLMUserMessage)
        ):
            schema_instruction = (
                "\n\nWhen done using tools, provide your final answer as valid JSON "
                "(no markdown fences) matching this schema:\n"
                "<output_schema>\n"
                + json.dumps(request.structured_output, indent=2)
                + "\n</output_schema>"
            )
            injected_prompt = LLMUserMessage(
                content=request.prompt.content + schema_instruction
            )
            content[-1] = _transform_content(injected_prompt)

        try:
            response = await self._client.models.generate_content(
                model=config.name,
                contents=content,
                config=types.GenerateContentConfig(**generation),
            )
        except genai_errors.APIError as e:
            if 400 <= e.code < 500:
                raise LLMClientError(e.code, e.message if e.message else "")
            if 500 <= e.code < 600:
                raise LLMServerError(e.code, e.message if e.message else "")
            raise LLMError(e.code, e.message if e.message else "")

        except Exception as e:
            raise LLMError(601, str(e))

        # check if there is a content:
        if (
            not isinstance(response, types.GenerateContentResponse)
            or not response.candidates
            or not response.candidates[0]
        ):
            raise LLMError(603, "No content returned from Google API")

        # check if there was a function call:
        if response.function_calls:
            original_content = LLMOriginalContent(
                provider="google", content=response.candidates[0].content
            )
            calls: list[LLMFunctionCall] = []
            # Iterate over parts directly: thought_signature is a Part field,
            # not a FunctionCall field, so response.function_calls loses it.
            for part in response.candidates[0].content.parts:  # type: ignore
                if part.function_call is None:
                    continue
                fc = part.function_call
                if not fc.name:
                    raise LLMError(603, "No function name returned from Google API")
                if (
                    request.allowed_tools is None
                    or fc.name not in request.allowed_tools
                ):
                    raise LLMError(603, f"Function call not allowed: {fc.name}")
                calls.append(
                    LLMFunctionCall(
                        name=fc.name,
                        arguments=fc.args or {},
                        original_content=original_content,
                        thought_signature=part.thought_signature,
                    )
                )

            if len(calls) == 1:
                return LLMResponse(response=calls[0], id=request.id)

            return LLMResponse(
                response=LLMFunctionCallBatch(
                    calls=calls,
                    original_content=original_content,
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

        raise LLMError(
            603, "LLM response didn't contain any content.\nResponse: " + str(response)
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

        case LLMSystemMessage(content=c):
            return types.UserContent(parts=[types.Part.from_text(text=c)])

        case LLMAssistantMessage(content=c):
            return types.Content(
                role="model",
                parts=[types.Part.from_text(text=str(c))],
            )

        case LLMFunctionCall(name=fnc_name, arguments=fnc_args, thought_signature=sig):
            return types.ModelContent(
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(name=fnc_name, args=fnc_args),
                        thought_signature=sig,
                    )
                ]
            )

        case LLMFunctionCallBatch(calls=calls):
            return types.ModelContent(
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(name=c.name, args=c.arguments),
                        thought_signature=c.thought_signature,
                    )
                    for c in calls
                ]
            )

        case LLMFunctionResponse(call=call, response=response):
            return types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(name=call.name, response=response)
                ],
            )

        case LLMFunctionResponseBatch(responses=responses):
            return types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name=r.call.name, response=r.response
                    )
                    for r in responses
                ],
            )

        case _:
            raise TypeError(
                f"Unsupported message type for Google transform: {type(content).__name__}"
            )
