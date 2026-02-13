from unittest.mock import AsyncMock, patch

import pytest
from google.genai import errors as genai_errors

from docai.llm.datatypes import LLMProviderConfig
from docai.llm.errors import LLMClientError
from docai.llm.google_provider import GoogleClient


@pytest.fixture
def custom_function_one():
    return {
        "name": "get_current_weather",
        "description": "Get the current weather in a given location",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA",
                }
            },
            "required": ["location"],
        },
    }


@pytest.fixture
def custom_function_two():
    return {
        "name": "send_email",
        "description": "Sends an email to a recipient.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "The email address of the recipient.",
                },
                "subject": {
                    "type": "string",
                    "description": "The subject line of the email.",
                },
                "body": {
                    "type": "string",
                    "description": "The content of the email.",
                },
            },
            "required": ["recipient", "subject", "body"],
        },
    }


@pytest.fixture
def custom_function_three():
    return {
        "name": "get_news_headlines",
        "description": "Gets the latest news headlines for a given topic.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": 'The topic to search for, e.g. "technology" or "sports".',
                },
            },
            "required": ["topic"],
        },
    }


@pytest.mark.asyncio
async def test_google_client_init_empty_key_fails():
    """Tests that initialization fails if the API key is missing."""

    with pytest.raises(ValueError):
        GoogleClient(config=LLMProviderConfig(name="google", api_key=""))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "api_key",
    ["invalid_api_key", "error", "something random", "xxxx-xxxx-xxxx-xxxx-xxxx"],
)
async def test_google_client_invalid_api_key(api_key):
    """Tests that LLMClientError is raised for an invalid API key."""
    client = GoogleClient(config=LLMProviderConfig(name="google", api_key=api_key))

    with patch.object(
        client._client.models, "list", new_callable=AsyncMock
    ) as mock_list:
        mock_list.side_effect = (genai_errors.APIError(code=400, response_json={}),)

        with pytest.raises(LLMClientError) as excinfo:
            await client._validate()

    # Assert that the captured exception has the code we simulated.
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
@patch("docai.llm.google_provider.genai.Client")  # A regular patch is fine here
async def test_google_client_initialization_succeeds(mock_genai_client):
    """Tests successful GoogleClient initialization."""

    mock_aio_client = AsyncMock()
    mock_aio_client.models.list.return_value = None  # Simulate successful API call
    mock_genai_client.return_value.aio = mock_aio_client

    client = await GoogleClient.create(
        config=LLMProviderConfig(name="google", api_key="a-valid-key")
    )

    mock_aio_client.models.list.assert_awaited_once()
    assert isinstance(client, GoogleClient)


# for the init we need check if the tools are set right.


@pytest.mark.asyncio
# @pytest.mark.parametrize()
async def test_google_client_set_tools():
    # TODO: finish this test
    client = await GoogleClient.create(
        config=LLMProviderConfig(name="google", api_key="a-valid-key")
    )
    # assert client.tools == ["google-search", "google-translate"]
