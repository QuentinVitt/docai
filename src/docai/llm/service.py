from __future__ import annotations

import asyncio
import uuid
from logging import getLogger
from typing import Callable, Optional

from docai.config.datatypes import LLMConfig, LLMModelConfig
from docai.llm.cache import LLMCache
from docai.llm.client import LLMClient, create_client
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMFunctionCall,
    LLMFunctionCallBatch,
    LLMFunctionResponse,
    LLMFunctionResponseBatch,
    LLMMessage,
    LLMProviderMessage,
    LLMRequest,
    LLMUserMessage,
)
from docai.llm.errors import LLMError
from docai.llm.runner import run

logger = getLogger(__name__)


class LLMService:
    def __init__(self, config: LLMConfig):
        self._connections: list[tuple[LLMClient, LLMModelConfig]] = []
        self._config: LLMConfig = config

        # set up cache
        self._cache = LLMCache(self._config.cache)

        # set up tools
        self._tools: Optional[dict[str, dict]] = None

    @classmethod
    async def create(
        cls, config: LLMConfig, tools: Optional[dict[str, dict]] = None
    ) -> LLMService:
        """Creates and initializes an LLMService with clients for each profile."""
        service = cls(config)
        service._tools = tools
        for profile in config.profiles:
            try:
                client = await create_client(profile.provider, tools)
                service._connections.append((client, profile.model))
            except LLMError as e:
                logger.warning(
                    "Failed to create client for provider %s: %s",
                    profile.provider.name,
                    e,
                )

        if not service._connections:
            logger.error("Failed to create LLMService: no clients could be initialized")
            raise LLMError(
                608, "Failed to create LLMService: no clients could be initialized"
            )

        return service

    async def close(self):
        """Closes all client connections."""
        try:
            close_tasks = [client.close() for client, _ in self._connections]
            await asyncio.gather(*close_tasks)
            logger.debug("All LLM clients closed.")
        except Exception as e:
            logger.error("Failed to close LLM clients", exc_info=e)
            raise LLMError(609, "Failed to close LLM clients")

    async def _generate(
        self,
        client: LLMClient,
        model_config: LLMModelConfig,
        request: LLMRequest,
        bypass_cache: bool = False,
    ) -> tuple[str | dict, LLMProviderMessage]:
        result = await run(
            self._cache,
            request,
            model_config,
            client,
            self._config.retry,
            self._config.concurrency.concurrency_semaphore,
            bypass_cache=bypass_cache,
        )
        if isinstance(result.response, LLMAssistantMessage):
            return result.response.content, result.response
        elif isinstance(result.response, LLMFunctionCall):
            return {
                "function_call": {
                    "name": result.response.name,
                    "arguments": result.response.arguments,
                }
            }, result.response
        elif isinstance(result.response, LLMFunctionCallBatch):
            return {
                "function_calls": [
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in result.response.calls
                ]
            }, result.response

        raise LLMError(601, "Unsupported response type: " + str(type(result.response)))

    async def generate(
        self,
        prompt: str | LLMUserMessage | LLMRequest,
        system_prompt: Optional[str] = None,
        history: Optional[list[LLMMessage]] = None,
        structured_output: Optional[dict] = None,
        id: Optional[uuid.UUID] = None,
        bypass_cache: bool = False,
        response_validator: Optional[Callable[[str | dict], str | None]] = None,
    ) -> tuple[str | dict, LLMProviderMessage]:

        if isinstance(prompt, LLMRequest):
            request = prompt
        else:
            request_args = {
                "prompt": prompt
                if isinstance(prompt, LLMUserMessage)
                else LLMUserMessage(content=prompt),
                "history": history if history else [],
            }
            if system_prompt:
                request_args["system_prompt"] = system_prompt
            if structured_output:
                request_args["structured_output"] = structured_output
            if id:
                request_args["id"] = id
            if response_validator:
                request_args["response_validator"] = response_validator
            request = LLMRequest(**request_args)

        # go over all connections with request. return first hit
        for client, model_config in self._connections:
            try:
                return await self._generate(client, model_config, request, bypass_cache)
            except Exception as e:
                logger.warning(
                    f"Failed to generate request {request} with {client}, {model_config}",
                    exc_info=e,
                )
        logger.error(f"Failed to generate request {request} with all connections")
        raise LLMError(610, "Failed to generate response with all connections")

    async def generate_agent(
        self,
        prompt: str | LLMUserMessage | LLMRequest,
        system_prompt: Optional[str] = None,
        history: Optional[list[LLMMessage]] = None,
        allowed_tools: Optional[set[str]] = None,
        structured_output: Optional[dict] = None,
        max_turns: int = 10,
        id: Optional[uuid.UUID] = None,
        bypass_cache: bool = False,
        response_validator: Optional[Callable[[str | dict], str | None]] = None,
    ) -> tuple[str | dict, LLMProviderMessage]:

        # Build initial request.
        # When tools + structured output are both requested, embed the JSON schema
        # in the prompt text instead of using the provider's structured output mode
        # (Google API doesn't support both simultaneously).
        if isinstance(prompt, LLMRequest):
            request = prompt
        else:
            prompt_msg = (
                LLMUserMessage(content=prompt) if isinstance(prompt, str) else prompt
            )
            request_args: dict = {
                "prompt": prompt_msg,
                "history": history if history else [],
            }
            if system_prompt:
                request_args["system_prompt"] = system_prompt
            if allowed_tools:
                request_args["allowed_tools"] = allowed_tools
            if structured_output:
                request_args["structured_output"] = structured_output
            if id:
                request_args["id"] = id
            if response_validator:
                request_args["response_validator"] = response_validator
            request = LLMRequest(**request_args)

        # Agent loop: outer loop over connections, inner loop over turns.
        # Running all turns against one connection before trying the next ensures
        # conversation history is always consistent with one model — critical for
        # thinking models whose thought_signatures are model-specific.
        for client, model_config in self._connections:
            current_request = request
            try:
                for turn in range(max_turns):
                    parsed_result, raw_result = await self._generate(
                        client, model_config, current_request, bypass_cache
                    )

                    # Reason: text response — agent is done
                    if isinstance(raw_result, LLMAssistantMessage):
                        return parsed_result, raw_result

                    # Act + Observe: single tool call — execute and continue
                    if isinstance(raw_result, LLMFunctionCall):
                        function_response = await self._execute_tool(raw_result)
                        current_request = LLMRequest(
                            prompt=function_response,
                            system_prompt=current_request.system_prompt,
                            history=list(current_request.history) + [current_request.prompt, raw_result],
                            allowed_tools=current_request.allowed_tools,
                            structured_output=current_request.structured_output,
                            response_validator=current_request.response_validator,
                            id=current_request.id,
                        )
                        continue

                    # Act + Observe: parallel tool calls — execute all and continue
                    if isinstance(raw_result, LLMFunctionCallBatch):
                        responses = await asyncio.gather(
                            *[self._execute_tool(call) for call in raw_result.calls]
                        )
                        batch_response = LLMFunctionResponseBatch(responses=list(responses))
                        current_request = LLMRequest(
                            prompt=batch_response,
                            system_prompt=current_request.system_prompt,
                            history=list(current_request.history) + [current_request.prompt, raw_result],
                            allowed_tools=current_request.allowed_tools,
                            structured_output=current_request.structured_output,
                            response_validator=current_request.response_validator,
                            id=current_request.id,
                        )
                        continue

                    raise LLMError(601, "Unsupported response type: " + str(type(raw_result)))

                logger.warning(
                    "Agent exceeded maximum turns (%d) with %s, %s — trying next connection",
                    max_turns, client, model_config,
                )

            except LLMError as e:
                if e.status_code == 601:
                    raise
                logger.warning(
                    "Agent failed with %s, %s — trying next connection",
                    client, model_config, exc_info=e,
                )

        logger.error("Agent failed with all connections")
        raise LLMError(610, "Agent failed with all connections")

    async def _execute_tool(self, tool_call: LLMFunctionCall) -> LLMFunctionResponse:
        tools = self._tools
        if tools is None or tool_call.name not in tools:
            logger.debug(
                "Called tool '%s' for llm function callnot found in registry",
                tool_call.name,
            )
            return LLMFunctionResponse(
                call=tool_call,
                response={"error": f"Tool '{tool_call.name}' not found in registry"},
            )

        try:
            result = tools[tool_call.name]["callable"](**tool_call.arguments)
            return LLMFunctionResponse(call=tool_call, response={"result": result})
        except Exception as e:
            logger.debug(
                "Tool '%s' raised an exception for llm function call: %s",
                tool_call.name,
                str(e),
                exc_info=e,
            )
            return LLMFunctionResponse(call=tool_call, response={"error": str(e)})
