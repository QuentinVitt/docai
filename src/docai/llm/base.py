import asyncio
import logging
from importlib import resources
from typing import AsyncIterable, AsyncIterator

import yaml

from docai.llm.llm_client import LLMClient, LLMRequest, LLMResponse

logger = logging.getLogger("docai_project")

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "llm_config.yaml"

max_concurrency = 10

try:
    llm_config_raw = resources.open_text(CONFIG_PACKAGE, CONFIG_FILE)
except FileNotFoundError:
    logger.critical("Logging configuration file not found", exc_info=True)
    exit(1)

llm_config = yaml.safe_load(llm_config_raw)


async def run_llm(
    requests: AsyncIterable[LLMRequest],
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
            clients[provider] = LLMClient(provider)
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
