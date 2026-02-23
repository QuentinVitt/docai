from unittest.mock import patch

import pytest

from docai.llm.client import create_client
from docai.llm.datatypes import LLMProviderConfig
from docai.llm.errors import LLMError
from docai.llm.google_provider import GoogleClient


@pytest.mark.asyncio
@patch(
    "docai.llm.google_provider.GoogleClient._validate",
    async_mock=True,
    return_value=None,
)
async def test_create_google_client(mock_validate):
    config = LLMProviderConfig(name="google", api_key="my_api_key")

    client = await create_client(config)

    assert isinstance(client, GoogleClient)


@pytest.mark.asyncio
async def test_create_false_client():
    config = LLMProviderConfig(name="non_existing", api_key="my_api_key")

    with pytest.raises(LLMError) as exc_info:
        await create_client(config)

    assert exc_info.value.status_code == 600
