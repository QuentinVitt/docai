import asyncio
import logging
from typing import AsyncIterable, AsyncIterator

from docai.llm.llm_client import LLMClient

logger = logging.getLogger("docai_project")


async def run_llm(
    requests: AsyncIterable[list[dict[str, str]]],
    usecase: str | None = None,
    model: str | None = None,
    agent_mode: bool = False,
) -> AsyncIterator[tuple[bool, str | None]]:
    """
    Lazily process LLM requests from an async iterable and yield results as they complete.
    Each yielded item matches the LLMClient.call_llm return (function_call flag, text).
    """
    client = LLMClient(model=model, usecase=usecase, agent_mode=agent_mode)
    semaphore = asyncio.Semaphore(10)

    async def _handle(contents: list[dict[str, str]]) -> tuple[bool, str | None]:
        async with semaphore:
            return await client.call_llm(contents)

    async for contents in requests:
        try:
            yield await _handle(contents)
        except Exception:
            logger.exception("LLM request failed")
            raise

    # TODO: retries
    # TODO: max in-flight requests / backpressure
    # TODO: optional per-request error handling strategy
