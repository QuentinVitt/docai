from unittest.mock import AsyncMock, patch

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMFunctionCall,
    LLMModelConfig,
    LLMOriginalContent,
    LLMProviderConfig,
    LLMRequest,
    LLMResponse,
    LLMUserMessage,
)
from docai.llm.errors import LLMClientError, LLMError, LLMServerError
from docai.llm.google_provider import GoogleClient


@pytest.fixture
def valid_provider_config():
    return LLMProviderConfig(name="google", api_key="a-valid-key")


@pytest.fixture
def simple_model_config():
    return LLMModelConfig(name="gemini-2.5-flash")


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
async def test_google_client_initialization_succeeds(
    mock_genai_client, valid_provider_config
):
    """Tests successful GoogleClient initialization."""

    mock_aio_client = AsyncMock()
    mock_aio_client.models.list.return_value = None  # Simulate successful API call
    mock_genai_client.return_value.aio = mock_aio_client

    client = await GoogleClient.create(config=valid_provider_config)

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
async def test_google_client_set_tools(function_declarations, valid_provider_config):
    tools, validate = {}, {}
    for function_declaration_json, function_declaration_type in function_declarations:
        name = function_declaration_json["name"]
        tools[name] = function_declaration_json
        validate[name] = function_declaration_type

    client = GoogleClient(
        config=valid_provider_config,
        custom_tools=tools,
    )

    assert len(client._custom_tools) == len(validate)

    for name, fnc in validate.items():
        assert name in client._custom_tools
        assert client._custom_tools[name] == fnc


@pytest.mark.asyncio
async def test_google_client_close(valid_provider_config):
    client = GoogleClient(config=valid_provider_config)

    await client.close()

    assert client._closed

    with pytest.raises(RuntimeError) as exc_info:
        await client._client.models.list()

        assert (
            "RuntimeError: Cannot send a request, as the client has been closed."
            == exc_info.value
        )


# OK, now we need generation tests. Lets first think about a few


# single input tests.
@pytest.mark.asyncio
async def test_google_client_generation_simple(
    valid_provider_config, simple_model_config
):

    client = GoogleClient(config=valid_provider_config)

    message = LLMUserMessage(content="Why is the sky blue?")
    request = LLMRequest(prompt=message)

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        response_from_generate = types.GenerateContentResponse(
            automatic_function_calling_history=[],
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(
                                text="""The sky is blue because of a phenomenon called **Rayleigh scattering**."""
                            ),
                        ],
                        role="model",
                    ),
                )
            ],
        )
        mock_generate_content.return_value = response_from_generate

        response = await client.generate(request, simple_model_config)

        assert isinstance(response, LLMResponse)

        mock_generate_content.assert_called_once_with(
            model=simple_model_config.name,
            contents=[
                types.UserContent(
                    parts=[types.Part.from_text(text="Why is the sky blue?")]
                )
            ],
            config=types.GenerateContentConfig(**{}),
        )

        expected_response = LLMResponse(
            response=LLMAssistantMessage(
                original_content=LLMOriginalContent(
                    provider="google",
                    content=types.Content(
                        parts=[
                            types.Part(
                                text="""The sky is blue because of a phenomenon called **Rayleigh scattering**."""
                            ),
                        ],
                        role="model",
                    ),
                ),
                content="The sky is blue because of a phenomenon called **Rayleigh scattering**.",
            ),
            id=request.id,
        )

        assert expected_response == response


# multi conversation test
@pytest.mark.asyncio
async def test_google_client_generation_multi(
    valid_provider_config, simple_model_config
):

    client = GoogleClient(config=valid_provider_config)

    request = LLMRequest(
        prompt=LLMUserMessage(content="What about birds?"),
        history=[
            LLMUserMessage(content="Why is the sky blue?"),
            LLMAssistantMessage(
                content="Because of Rayleigh scattering.",
                original_content=LLMOriginalContent(provider="antropic", content="..."),
            ),
        ],
    )

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        response_from_generate = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[types.Part(text="Birds are diverse.")], role="model"
                    )
                )
            ]
        )

        mock_generate_content.return_value = response_from_generate

        response = await client.generate(request, simple_model_config)

        mock_generate_content.assert_called_once_with(
            model=simple_model_config.name,
            contents=[
                types.UserContent(
                    parts=[types.Part.from_text(text="Why is the sky blue?")]
                ),
                types.Content(
                    parts=[types.Part(text="Because of Rayleigh scattering.")],
                    role="model",
                ),
                types.UserContent(
                    parts=[types.Part.from_text(text="What about birds?")]
                ),
            ],
            config=types.GenerateContentConfig(**{}),
        )

        expected_response = LLMResponse(
            response=LLMAssistantMessage(
                content="Birds are diverse.",
                original_content=LLMOriginalContent(
                    provider="google",
                    content=types.Content(
                        parts=[types.Part(text="Birds are diverse.")], role="model"
                    ),
                ),
            ),
            id=request.id,
        )

        assert expected_response == response


# function_call test


@pytest.mark.asyncio
async def test_google_client_generation_function_call(
    valid_provider_config, simple_model_config, custom_function_one
):

    custom_tool_dict = {custom_function_one[0]["name"]: custom_function_one[0]}

    client = GoogleClient(config=valid_provider_config, custom_tools=custom_tool_dict)

    request = LLMRequest(
        prompt=LLMUserMessage(content="What is the weather in Boston, MA?"),
        allowed_tools={"get_current_weather"},
    )

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        response_from_generate = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name="get_current_weather",
                                    args={"location": "Boston, MA"},
                                )
                            )
                        ],
                        role="model",
                    )
                )
            ]
        )
        assert response_from_generate.candidates
        mock_generate_content.return_value = response_from_generate

        response = await client.generate(request, simple_model_config)

        mock_generate_content.assert_called_once_with(
            model=simple_model_config.name,
            contents=[
                types.UserContent(
                    parts=[
                        types.Part.from_text(text="What is the weather in Boston, MA?")
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=[custom_function_one[1]])]
            ),
        )

        expected_response = LLMResponse(
            response=LLMFunctionCall(
                name="get_current_weather",
                arguments={"location": "Boston, MA"},
                original_content=LLMOriginalContent(
                    provider="google",
                    content=response_from_generate.candidates[0].content,
                ),
            ),
            id=request.id,
        )

        assert expected_response == response


# structured output test


@pytest.mark.asyncio
async def test_google_client_generation_structured_output(
    valid_provider_config, simple_model_config
):

    client = GoogleClient(config=valid_provider_config)

    json_schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}, "temperature": {"type": "number"}},
    }

    request = LLMRequest(
        prompt=LLMUserMessage(content="What is the weather in Boston?"),
        structured_output=json_schema,
    )

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        response_from_generate = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(text='{"city": "Boston", "temperature": 72}')
                        ],
                        role="model",
                    )
                )
            ]
        )
        assert response_from_generate.candidates
        mock_generate_content.return_value = response_from_generate

        response = await client.generate(request, simple_model_config)

        mock_generate_content.assert_called_once()

        _, kwargs = mock_generate_content.call_args

        config_arg = kwargs["config"]

        assert config_arg.response_mime_type == "application/json"

        assert config_arg.response_json_schema == json_schema

        expected_response = LLMResponse(
            response=LLMAssistantMessage(
                content='{"city": "Boston", "temperature": 72}',
                original_content=LLMOriginalContent(
                    provider="google",
                    content=response_from_generate.candidates[0].content,
                ),
            ),
            id=request.id,
        )

        assert expected_response == response


# model generation config variation test


@pytest.mark.asyncio
async def test_google_client_generation_model_config_variation(
    valid_provider_config,
):

    client = GoogleClient(config=valid_provider_config)

    model_config = LLMModelConfig(
        name="gemini-2.5-flash", generation={"temperature": 0.8, "top_p": 0.9}
    )

    request = LLMRequest(prompt=LLMUserMessage(content="Tell me a story."))

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        response_from_generate = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[types.Part(text="Once upon a time...")], role="model"
                    )
                )
            ]
        )

        mock_generate_content.return_value = response_from_generate

        await client.generate(request, model_config)

        mock_generate_content.assert_called_once()

        _, kwargs = mock_generate_content.call_args

        config_arg = kwargs["config"]

        assert config_arg.temperature == 0.8

        assert config_arg.top_p == 0.9


@pytest.mark.parametrize(
    "generation_return_value",
    [
        None,
        "random_return",
        45,
        {"test": "value"},
        types.GenerateContentResponse(),
        types.GenerateContentResponse(candidates=[]),
        types.GenerateContentResponse(candidates=[types.Candidate()]),
        types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content())]
        ),
        types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(parts=[]))]
        ),
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[types.Part.from_function_call(name="", args={})]
                    )
                )
            ]
        ),
    ],
)
@pytest.mark.asyncio
async def test_google_client_generation_false_responses(
    valid_provider_config, simple_model_config, generation_return_value
):
    client = GoogleClient(config=valid_provider_config)
    request = LLMRequest(prompt=LLMUserMessage(content="Tell me a story."))

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        mock_generate_content.return_value = generation_return_value

        with pytest.raises(LLMError) as exc_info:
            await client.generate(request, simple_model_config)

        assert exc_info.value.status_code == 603


@pytest.mark.parametrize(
    "error_type",
    [
        (400, LLMClientError),
        (429, LLMClientError),
        (500, LLMServerError),
        (503, LLMServerError),
        (601, LLMError),
        (300, LLMError),
    ],
)
@pytest.mark.asyncio
async def test_google_client_generation_errors(
    valid_provider_config, simple_model_config, error_type
):
    client = GoogleClient(config=valid_provider_config)
    request = LLMRequest(prompt=LLMUserMessage(content="Tell me a story."))

    with patch.object(
        client._client.models, "generate_content", new_callable=AsyncMock
    ) as mock_generate_content:
        mock_generate_content.side_effect = genai_errors.APIError(
            code=error_type[0], response_json={}
        )

        with pytest.raises(error_type[1]) as exc_info:
            await client.generate(request, simple_model_config)

        assert exc_info.value.status_code == error_type[0]
