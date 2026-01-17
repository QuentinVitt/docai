import logging
import os
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from docai.llm.agent_tools import TOOL_REGISTRY
from docai.llm.llm_datatypes import (
    LLMClientError,
    LLMError,
    LLMFunctionRequest,
    LLMFunctionResponse,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMServerError,
)

logger = logging.getLogger("docai_project")


def configure_google_client(provider_config: dict):
    logger.debug("Configuring Google client")
    api_key_name = provider_config.get('api_key_env', 'GEMINI_API_KEY')
    logger.debug("Using API key from env '%s'", api_key_name)
    api_key = os.environ.get(api_key_name)
    if not api_key:
        logger.error("Google API key env '%s' is not set", api_key_name)
        raise ValueError(f"API key {api_key_name} not set")
    try:
        client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(async_client_args={})
        ).aio

        async def cleanup():
            await client.aclose()

        logger.debug("Google async client created")
        return client, cleanup

    except genai_errors.APIError as e:
        if 400 <= e.code < 500:
            logger.error("Google API client error (code %s): %s", e.code, e.message)
            raise LLMClientError(e.code, e.message if e.message else "")
        elif 500 <= e.code < 600:
            logger.error("Google API server error (code %s): %s", e.code, e.message)
            raise LLMServerError(e.code, e.message if e.message else "")

        logger.error("Google API error (code %s): %s", e.code, e.message)
        raise LLMError(
            e.code,
            e.message if e.message else "",
        )

    except Exception as e:
        logger.exception("Unexpected error configuring Google client: %s", e)
        raise LLMError(601, f"Unexpected error: {e}")


def configure_google_call_llm(client):
    async def wrapper(
        request: LLMRequest, model: str, model_config: dict[str, Any] | None = None
    ) -> LLMResponse:
        # Keep wrapper async; offload sync SDK call to a thread
        # Copy so we don't mutate caller-provided config
        model_config = dict(model_config) if model_config else {}
        if request.system_prompt:
            model_config["system_instruction"] = request.system_prompt
            logger.debug("System instruction set for request %s", request.request_id)
        if request.structured_output:
            model_config["response_mime_type"] = "application/json"
            model_config["response_json_schema"] = request.structured_output
            logger.debug(
                "Structured output configured for request %s", request.request_id
            )
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
                logger.debug(
                    "Enabled %d agent function(s) for request %s",
                    len(function_decls),
                    request.request_id,
                )

        # setup the content:
        try:
            google_contents = [
                google_content_from_dict(message) for message in request.contents
            ]
            logger.debug(
                "Converted contents for request %s to Google format",
                request.request_id,
            )
        except ValueError as e:
            logger.error(
                "Failed to convert contents for request %s: %s",
                request.request_id,
                str(e),
            )
            raise LLMError(602, str(e))
        except Exception as e:
            logger.exception(
                "Unexpected error converting contents for request %s: %s",
                request.request_id,
                str(e),
            )
            raise LLMError(601, str(e))

        try:
            logger.debug(
                "Sending request %s to model '%s'",
                request.request_id,
                model,
            )
            response = await client.models.generate_content(
                model=model,
                contents=google_contents,
                config=types.GenerateContentConfig(**model_config),
            )
            logger.debug("Received response for request %s", request.request_id)
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

        # Check if there is a response:
        if not (
            response
            and response.candidates
            and response.candidates[0]
            and response.candidates[0].content
            and response.candidates[0].content.parts
            and response.candidates[0].content.parts[0]
        ):
            logger.error(
                "Response for request %s is missing content or has invalid structure: %s",
                request.request_id,
                str(response),
            )
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
            logger.debug("Function call received for request %s", request.request_id)
            if not response.candidates[0].content.parts[0].function_call.name:
                logger.error(
                    "Function call in response for request %s is missing name",
                    request.request_id,
                )
                raise LLMError(
                    603,
                    "response specified a function call without a name.\nResponse: "
                    + str(response),
                )

            content = LLMFunctionRequest(
                name=response.candidates[0].content.parts[0].function_call.name,
                args=response.candidates[0].content.parts[0].function_call.args,
            )

            logger.debug(
                "Parsed function call for request %s: %s",
                request.request_id,
                content,
            )

            return LLMResponse(
                request_id=request.request_id,
                response=LLMMessage(
                    role=LLMRole.FUNCTIONREQ,
                    content=content,
                    original_content=('google', response.candidates[0].content),
                ),
            )

        # Check if there was a normal response:
        if response.text:
            return LLMResponse(
                request_id=request.request_id,
                response=LLMMessage(
                    role=LLMRole.ASSISTANT,
                    content=response.text,
                    original_content=('google', response.candidates[0].content),
                ),
            )

        logger.error(
            "Response for request %s did not contain any text content: %s",
            request.request_id,
            str(response),
        )
        raise LLMError(
            602, "response didn't contain any content.\nResponse: " + str(response)
        )

    return wrapper


def google_content_from_dict(message: LLMMessage) -> types.Content:
    """
    Translate an internal LLMMessage into a Google Content object.
    Ensures text parts are strings and handles function call payloads explicitly.
    """

    match message.role:
        case LLMRole.USER:
            if not isinstance(message.content, str):
                logger.error(
                    "Invalid user content type: %s",
                    type(message.content).__name__,
                )
                raise ValueError(
                    f"User content must be text, got {type(message.content).__name__}"
                )

            logger.debug("Mapping USER message to Content")
            return types.UserContent(parts=[types.Part.from_text(text=message.content)])

        case LLMRole.ASSISTANT:
            if message.original_content is not None and message.original_content[0] == "google":
                logger.debug("Using original assistant content passthrough")
                return message.original_content[1]

            if not isinstance(message.content, str):
                logger.error(
                    "Invalid assistant content type: %s",
                    type(message.content).__name__,
                )
                raise ValueError(
                    f"Assistant content must be text, got {type(message.content).__name__}"
                )

            logger.debug("Mapping ASSISTANT message to Content")
            return types.Content(
                role="model",
                parts=[types.Part.from_text(text=message.content)],
            )

        case LLMRole.SYSTEM:
            logger.error("System content not supported for Google provider")
            raise ValueError("System content not supported for google llm")

        case LLMRole.FUNCTIONREQ:
            if message.original_content is not None and message.original_content[0] == "google":
                logger.debug("Using original function request content passthrough")
                return message.original_content[1]

            if not isinstance(message.content, LLMFunctionRequest):
                logger.error(
                    "Invalid function request content type: %s",
                    type(message.content).__name__,
                )
                raise ValueError(
                    f"Function request content must be LLMFunctionRequest, got {type(message.content).__name__}"
                )

            logger.debug("Mapping FUNCTIONREQ message to model function call")
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
                logger.error(
                    "Invalid function response content type: %s",
                    type(message.content).__name__,
                )
                raise ValueError(
                    f"Function response content must be LLMFunctionResponse, got {type(message.content).__name__}"
                )

            logger.debug("Mapping FUNCTIONRESP message to function response part")
            function_response_part = types.Part.from_function_response(
                name=message.content.name,
                response={"result": message.content.result},
            )
            return types.Content(role="user", parts=[function_response_part])

        case _:
            logger.error("Undefined role for content: %s", message.role)
            raise ValueError(f"Undefined role for content: {message.role}")
