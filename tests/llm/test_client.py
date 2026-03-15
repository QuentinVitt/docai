from unittest.mock import AsyncMock, patch

import pytest

from docai.config.datatypes import LLMProviderConfig
from docai.llm.client import create_client
from docai.llm.errors import LLMError
from docai.llm.google_provider import GoogleClient


@pytest.mark.asyncio
@patch(
    "docai.llm.google_provider.GoogleClient._validate",
    new_callable=AsyncMock,
)
async def test_create_google_client(mock_validate):
    config = LLMProviderConfig(name="google", api_key="my_api_key")

    client = await create_client(config)

    assert isinstance(client, GoogleClient)


@pytest.mark.asyncio
@patch(
    "docai.llm.google_provider.GoogleClient._validate",
    new_callable=AsyncMock,
)
async def test_create_google_client_with_tools(mock_validate):
    config = LLMProviderConfig(name="google", api_key="my_api_key")
    tools = {
        "write": {"schema": {"name": "write", "description": "Write something"}, "callable": None},
        "read": {"schema": {"name": "read", "description": "Read something"}, "callable": None},
    }
    client = await create_client(config, tools)

    assert isinstance(client, GoogleClient)
    for key in tools.keys():
        assert key in client._custom_tools


@pytest.mark.asyncio
async def test_create_false_client():
    config = LLMProviderConfig(name="non_existing", api_key="my_api_key")

    with pytest.raises(LLMError) as exc_info:
        await create_client(config)

    assert exc_info.value.status_code == 600
