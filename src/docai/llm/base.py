import asyncio
import logging
from typing import AsyncIterable, AsyncIterator

from docai.llm.llm_client import LLMClient, LLMRequest, LLMResponse

logger = logging.getLogger("docai_project")

max_concurrency = 10


async def run_llm(
    requests: AsyncIterable[LLMRequest],
    llm_config: dict,
) -> AsyncIterator[LLMResponse]:
    """
    Lazily process LLM requests from an async iterable and yield results as they complete.
    Each yielded item matches the LLMClient.call_llm return (function_call flag, text).
    """

    clients: dict[str, LLMClient] = {}
    pending: set[asyncio.Task[LLMResponse]] = set()

    async def handle(req: LLMRequest) -> LLMResponse:
        provider = llm_config["models"][req.model]["provider"]
        if provider not in clients:
            clients[provider] = LLMClient(provider, llm_config["providers"][provider])
        return await clients[provider].call_llm(req)

    async for req in requests:
        pending.add(asyncio.create_task(handle(req)))

        if len(pending) >= max_concurrency:
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                pending.remove(task)
                try:
                    response = task.result()
                    yield response
                except Exception as e:
                    yield LLMResponse(request_id=req.request_id, error=str(e))

    while pending:
        done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            pending.remove(task)
            try:
                response = task.result()
                yield response
            except Exception as e:
                yield LLMResponse(request_id="", error=str(e))

    # TODO: retries
    # TODO: max in-flight requests / backpressure
    # TODO: optional per-request error handling strategy
