from unittest.mock import AsyncMock, patch

import pytest
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from docai.llm.datatypes import LLMProviderConfig
from docai.llm.errors import LLMClientError
from docai.llm.google_provider import GoogleClient


@pytest.fixture
def custom_function_one():
    function_declaration = {
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
    return function_declaration, types.FunctionDeclaration(**function_declaration)


@pytest.fixture
def custom_function_two():
    function_declaration = {
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
    return function_declaration, types.FunctionDeclaration(**function_declaration)


@pytest.fixture
def custom_function_three():
    function_declaration = {
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
    return function_declaration, types.FunctionDeclaration(**function_declaration)


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


@pytest.fixture
def function_declarations(request):
    fixture_names = request.param
    return [request.getfixturevalue(name) for name in fixture_names]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "function_declarations",
    [
        [],
        ["custom_function_one"],
        ["custom_function_one", "custom_function_two"],
        ["custom_function_one", "custom_function_two", "custom_function_three"],
    ],
    indirect=True,
)
async def test_google_client_set_tools(function_declarations):
    tools, validate = {}, {}
    for function_declaration_json, function_declaration_type in function_declarations:
        name = function_declaration_json["name"]
        tools[name] = function_declaration_json
        validate[name] = function_declaration_type

    client = GoogleClient(
        config=LLMProviderConfig(name="google", api_key="a-valid-key"),
        custom_tools=tools,
    )

    assert len(client._custom_tools) == len(validate)

    for name, fnc in validate.items():
        assert name in client._custom_tools
        assert client._custom_tools[name] == fnc
