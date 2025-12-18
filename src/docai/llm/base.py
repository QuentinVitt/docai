import asyncio
import logging
import os
from importlib import resources

import yaml
from _typeshed import ExcInfo
from google import genai

logger = logging.getLogger("docai_project")

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "llm_config.yaml"


async def run_llm(
    contents: list[str],
    use_case: str | None = None,
    model: str | None = None,
    agent: bool = False,
):
    # Configure the llm

    # Call the configured llm
    # response = await call_llm()  # Simulates the delay of the LLM call
    raise NotImplementedError("run_llm is not implemented")
    # return response
