import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docai.config.datatypes import (
    LLMConcurrencyConfig,
    LLMConfig,
    LLMModelConfig,
    LLMProfileConfig,
    LLMProviderConfig,
    LLMRetryConfig,
)
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMFunctionCall,
    LLMFunctionResponse,
    LLMOriginalContent,
    LLMRequest,
    LLMResponse,
    LLMUserMessage,
)
from docai.llm.errors import LLMError
from docai.llm.service import LLMService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assistant_response(content="ok", req_id=None) -> LLMResponse:
    return LLMResponse(
        response=LLMAssistantMessage(
            content=content,
            original_content=LLMOriginalContent(provider="test", content=content),
        ),
        id=req_id or uuid.uuid4(),
    )


def _make_function_call_response(name="my_tool", args=None, req_id=None) -> LLMResponse:
    return LLMResponse(
        response=LLMFunctionCall(
            name=name,
            arguments=args or {},
            original_content=LLMOriginalContent(provider="test", content={}),
        ),
        id=req_id or uuid.uuid4(),
    )


def _make_profile(provider_name="google") -> LLMProfileConfig:
    return LLMProfileConfig(
        provider=LLMProviderConfig(name=provider_name, api_key="test-key"),
        model=LLMModelConfig(name="test-model"),
    )


def _make_config(profiles=None, tools=None) -> LLMConfig:
    return LLMConfig(
        profiles=profiles or [],
        concurrency=LLMConcurrencyConfig(
            max_concurrency=5,
            concurrency_semaphore=asyncio.Semaphore(5),
        ),
        retry=LLMRetryConfig(max_retries=3, retry_delay=0.1, max_validation_retries=2),
        cache=MagicMock(),
        tools=tools,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_service():
    """Factory: returns (service, [mock_clients], model_config).
    LLMCache is patched so no disk I/O occurs."""

    def _make(num_connections=1, tools=None):
        config = _make_config(tools=tools)
        with patch("docai.llm.service.LLMCache"):
            service = LLMService(config)

        model_config = LLMModelConfig(name="test-model")
        clients = []
        for _ in range(num_connections):
            client = MagicMock()
            client.close = AsyncMock()
            clients.append(client)

        service._connections = [(c, model_config) for c in clients]
        return service, clients, model_config

    return _make


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.LLMCache")
@patch("docai.llm.service.create_client", new_callable=AsyncMock)
async def test_create_builds_connections(mock_create_client, mock_cache):
    mock_create_client.return_value = MagicMock()
    config = _make_config(profiles=[_make_profile(), _make_profile()])

    service = await LLMService.create(config)

    assert len(service._connections) == 2
    assert mock_create_client.call_count == 2


@pytest.mark.asyncio
@patch("docai.llm.service.LLMCache")
@patch("docai.llm.service.create_client", new_callable=AsyncMock)
async def test_create_skips_failed_profile(mock_create_client, mock_cache):
    mock_create_client.side_effect = [
        LLMError(600, "provider not supported"),
        MagicMock(),
    ]
    config = _make_config(profiles=[_make_profile(), _make_profile()])

    service = await LLMService.create(config)

    assert len(service._connections) == 1


@pytest.mark.asyncio
@patch("docai.llm.service.LLMCache")
@patch("docai.llm.service.create_client", new_callable=AsyncMock)
async def test_create_raises_when_all_profiles_fail(mock_create_client, mock_cache):
    mock_create_client.side_effect = LLMError(600, "provider not supported")
    config = _make_config(profiles=[_make_profile()])

    with pytest.raises(LLMError) as exc_info:
        await LLMService.create(config)

    assert exc_info.value.status_code == 608


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_calls_all_clients(make_service):
    service, clients, _ = make_service(num_connections=2)

    await service.close()

    clients[0].close.assert_called_once()
    clients[1].close.assert_called_once()


@pytest.mark.asyncio
async def test_close_raises_on_exception(make_service):
    service, clients, _ = make_service(num_connections=2)
    clients[0].close.side_effect = Exception("connection reset")

    with pytest.raises(LLMError) as exc_info:
        await service.close()

    assert exc_info.value.status_code == 609


# ---------------------------------------------------------------------------
# _generate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_internal_text_response(mock_run, make_service):
    service, clients, model_config = make_service()
    response = _make_assistant_response("hello")
    mock_run.return_value = response

    request = LLMRequest(prompt=LLMUserMessage(content="test"))
    content, msg = await service._generate(clients[0], model_config, request)

    assert content == "hello"
    assert msg is response.response


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_internal_function_call_response(mock_run, make_service):
    service, clients, model_config = make_service()
    response = _make_function_call_response("my_tool", {"x": 1})
    mock_run.return_value = response

    request = LLMRequest(prompt=LLMUserMessage(content="test"))
    content, msg = await service._generate(clients[0], model_config, request)

    assert content == {"function_call": {"name": "my_tool", "arguments": {"x": 1}}}
    assert msg is response.response


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_internal_unsupported_response_type(mock_run, make_service):
    service, clients, model_config = make_service()
    mock_response = MagicMock(spec=LLMResponse)
    mock_response.response = MagicMock()  # not LLMAssistantMessage or LLMFunctionCall
    mock_run.return_value = mock_response

    request = LLMRequest(prompt=LLMUserMessage(content="test"))
    with pytest.raises(LLMError) as exc_info:
        await service._generate(clients[0], model_config, request)

    assert exc_info.value.status_code == 601


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_internal_bypass_cache_forwarded(mock_run, make_service):
    service, clients, model_config = make_service()
    mock_run.return_value = _make_assistant_response()

    request = LLMRequest(prompt=LLMUserMessage(content="test"))
    await service._generate(clients[0], model_config, request, bypass_cache=True)

    # bypass_cache passed as 7th positional arg
    assert mock_run.call_args.args[6] is True


# ---------------------------------------------------------------------------
# generate() — prompt building
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_str_prompt_wraps_in_user_message(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate("hello world")

    captured_request = mock_run.call_args.args[1]
    assert captured_request.prompt == LLMUserMessage(content="hello world")


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_user_message_passed_directly(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    user_msg = LLMUserMessage(content="hi")

    await service.generate(user_msg)

    captured_request = mock_run.call_args.args[1]
    assert captured_request.prompt is user_msg


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_llm_request_passed_directly(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    req = LLMRequest(prompt=LLMUserMessage(content="direct"))

    await service.generate(req)

    captured_request = mock_run.call_args.args[1]
    assert captured_request is req


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_with_system_prompt(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate("hello", system_prompt="be concise")

    captured_request = mock_run.call_args.args[1]
    assert captured_request.system_prompt == "be concise"


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_without_system_prompt(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate("hello")

    captured_request = mock_run.call_args.args[1]
    assert captured_request.system_prompt is None


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_with_history(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    history = [LLMUserMessage(content="prev")]

    await service.generate("hello", history=history)

    captured_request = mock_run.call_args.args[1]
    assert captured_request.history == history


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_with_structured_output(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    await service.generate("hello", structured_output=schema)

    captured_request = mock_run.call_args.args[1]
    assert captured_request.structured_output == schema


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_with_id(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    req_id = uuid.uuid4()

    await service.generate("hello", id=req_id)

    captured_request = mock_run.call_args.args[1]
    assert captured_request.id == req_id


# ---------------------------------------------------------------------------
# generate() — connection fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_first_connection_fails_fallback(mock_run, make_service):
    service, _, _ = make_service(num_connections=2)
    second_response = _make_assistant_response("from second")
    mock_run.side_effect = [LLMError(500, "server error"), second_response]

    content, _ = await service.generate("hello")

    assert content == "from second"
    assert mock_run.call_count == 2


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_all_connections_fail(mock_run, make_service):
    service, _, _ = make_service(num_connections=2)
    mock_run.side_effect = LLMError(500, "server error")

    with pytest.raises(LLMError) as exc_info:
        await service.generate("hello")

    assert exc_info.value.status_code == 610


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_bypass_cache_forwarded(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate("hello", bypass_cache=True)

    assert mock_run.call_args.args[6] is True


# ---------------------------------------------------------------------------
# generate_batch()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_batch_all_succeed(mock_run, make_service):
    service, _, _ = make_service()
    responses = [_make_assistant_response(f"r{i}") for i in range(3)]
    mock_run.side_effect = responses
    requests = [LLMRequest(prompt=LLMUserMessage(content=f"q{i}")) for i in range(3)]

    results = await service.generate_batch(requests)

    assert len(results) == 3
    assert all(isinstance(r, tuple) for r in results)
    assert [r[0] for r in results] == ["r0", "r1", "r2"]


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_batch_partial_failure(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.side_effect = [
        _make_assistant_response("r0"),
        LLMError(500, "server error"),
        _make_assistant_response("r2"),
    ]
    requests = [LLMRequest(prompt=LLMUserMessage(content=f"q{i}")) for i in range(3)]

    results = await service.generate_batch(requests)

    assert len(results) == 3
    assert isinstance(results[0], tuple) and results[0][0] == "r0"
    assert isinstance(results[1], LLMError)  # LLMError(610) from connection exhaustion
    assert isinstance(results[2], tuple) and results[2][0] == "r2"


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_generate_batch_empty_list(mock_run, make_service):
    service, _, _ = make_service()

    results = await service.generate_batch([])

    assert results == []
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# generate_agent() — prompt building
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_str_prompt_wraps_in_user_message(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate_agent("hello agent")

    captured_request = mock_run.call_args.args[1]
    assert captured_request.prompt == LLMUserMessage(content="hello agent")


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_user_message_passed_directly(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    user_msg = LLMUserMessage(content="hi agent")

    await service.generate_agent(user_msg)

    captured_request = mock_run.call_args.args[1]
    assert captured_request.prompt is user_msg


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_llm_request_passed_directly(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    req = LLMRequest(prompt=LLMUserMessage(content="direct agent"))

    await service.generate_agent(req)

    captured_request = mock_run.call_args.args[1]
    assert captured_request is req


# ---------------------------------------------------------------------------
# generate_agent() — turn logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_immediate_text_response(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response("done")

    content, msg = await service.generate_agent("start")

    assert content == "done"
    assert mock_run.call_count == 1


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_one_tool_call_then_text(mock_run, make_service):
    service, _, _ = make_service(
        tools={"my_tool": {"callable": lambda: "tool result", "schema": {}}}
    )
    req_id = uuid.uuid4()
    mock_run.side_effect = [
        _make_function_call_response("my_tool", {}, req_id),
        _make_assistant_response("final", req_id),
    ]

    content, _ = await service.generate_agent("start", id=req_id)

    assert content == "final"
    assert mock_run.call_count == 2

    second_request = mock_run.call_args_list[1].args[1]
    assert len(second_request.history) == 2
    assert second_request.history[0] == LLMUserMessage(content="start")
    assert isinstance(second_request.history[1], LLMFunctionCall)
    assert isinstance(second_request.prompt, LLMFunctionResponse)


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_history_grows_correctly(mock_run, make_service):
    """After 2 tool calls + 1 text: history on turn 3 has 4 entries."""
    service, _, _ = make_service(
        tools={"t": {"callable": lambda: "r", "schema": {}}}
    )
    req_id = uuid.uuid4()
    mock_run.side_effect = [
        _make_function_call_response("t", {}, req_id),
        _make_function_call_response("t", {}, req_id),
        _make_assistant_response("done", req_id),
    ]

    await service.generate_agent("go", id=req_id)

    third_request = mock_run.call_args_list[2].args[1]
    # history: [user_msg, tool_call_1, fn_response_1, tool_call_2]
    assert len(third_request.history) == 4
    assert third_request.history[0] == LLMUserMessage(content="go")
    assert isinstance(third_request.history[1], LLMFunctionCall)
    assert isinstance(third_request.history[2], LLMFunctionResponse)
    assert isinstance(third_request.history[3], LLMFunctionCall)


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_preserves_system_prompt_across_turns(mock_run, make_service):
    service, _, _ = make_service(
        tools={"t": {"callable": lambda: "r", "schema": {}}}
    )
    req_id = uuid.uuid4()
    mock_run.side_effect = [
        _make_function_call_response("t", {}, req_id),
        _make_assistant_response("done", req_id),
    ]

    await service.generate_agent("go", system_prompt="be brief", id=req_id)

    second_request = mock_run.call_args_list[1].args[1]
    assert second_request.system_prompt == "be brief"


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_preserves_request_id_across_turns(mock_run, make_service):
    service, _, _ = make_service(
        tools={"t": {"callable": lambda: "r", "schema": {}}}
    )
    req_id = uuid.uuid4()
    mock_run.side_effect = [
        _make_function_call_response("t", {}, req_id),
        _make_assistant_response("done", req_id),
    ]

    await service.generate_agent("go", id=req_id)

    second_request = mock_run.call_args_list[1].args[1]
    assert second_request.id == req_id


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_exceeds_max_turns(mock_run, make_service):
    service, _, _ = make_service(
        tools={"t": {"callable": lambda: "r", "schema": {}}}
    )
    req_id = uuid.uuid4()
    mock_run.return_value = _make_function_call_response("t", {}, req_id)

    with pytest.raises(LLMError) as exc_info:
        await service.generate_agent("go", max_turns=3, id=req_id)

    assert exc_info.value.status_code == 612
    assert mock_run.call_count == 3


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_all_connections_fail_on_turn(mock_run, make_service):
    service, _, _ = make_service(num_connections=2)
    mock_run.side_effect = LLMError(500, "server error")

    with pytest.raises(LLMError) as exc_info:
        await service.generate_agent("go")

    assert exc_info.value.status_code == 610


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_fallback_connection(mock_run, make_service):
    service, _, _ = make_service(num_connections=2)
    req_id = uuid.uuid4()
    mock_run.side_effect = [
        LLMError(500, "first connection down"),
        _make_assistant_response("from second", req_id),
    ]

    content, _ = await service.generate_agent("go", id=req_id)

    assert content == "from second"
    assert mock_run.call_count == 2


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_bypass_cache_forwarded(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate_agent("go", bypass_cache=True)

    assert mock_run.call_args.kwargs.get("bypass_cache") is True


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_allowed_tools_set_on_request(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()

    await service.generate_agent("go", allowed_tools={"my_tool"})

    captured_request = mock_run.call_args.args[1]
    assert captured_request.allowed_tools == {"my_tool"}


@pytest.mark.asyncio
@patch("docai.llm.service.run", new_callable=AsyncMock)
async def test_agent_structured_output_set_on_request(mock_run, make_service):
    service, _, _ = make_service()
    mock_run.return_value = _make_assistant_response()
    schema = {"type": "object"}

    await service.generate_agent("go", structured_output=schema)

    captured_request = mock_run.call_args.args[1]
    assert captured_request.structured_output == schema


# ---------------------------------------------------------------------------
# _execute_tool()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_success(make_service):
    service, _, _ = make_service(
        tools={"greet": {"callable": lambda name: f"hello {name}", "schema": {}}}
    )
    tool_call = LLMFunctionCall(
        name="greet",
        arguments={"name": "world"},
        original_content=LLMOriginalContent(provider="test", content={}),
    )

    response = await service._execute_tool(tool_call)

    assert response.call is tool_call
    assert response.response == {"result": "hello world"}


@pytest.mark.asyncio
async def test_execute_tool_arguments_forwarded(make_service):
    received = {}

    def _capture(**kwargs):
        received.update(kwargs)
        return "ok"

    service, _, _ = make_service(tools={"fn": {"callable": _capture, "schema": {}}})
    tool_call = LLMFunctionCall(
        name="fn",
        arguments={"x": 1, "y": 2},
        original_content=LLMOriginalContent(provider="test", content={}),
    )

    await service._execute_tool(tool_call)

    assert received == {"x": 1, "y": 2}


@pytest.mark.asyncio
async def test_execute_tool_not_found_tools_none(make_service):
    service, _, _ = make_service(tools=None)
    tool_call = LLMFunctionCall(
        name="missing",
        arguments={},
        original_content=LLMOriginalContent(provider="test", content={}),
    )

    response = await service._execute_tool(tool_call)

    assert "error" in response.response
    assert "missing" in response.response["error"]


@pytest.mark.asyncio
async def test_execute_tool_not_found_wrong_name(make_service):
    service, _, _ = make_service(tools={"other_tool": {"callable": lambda: None, "schema": {}}})
    tool_call = LLMFunctionCall(
        name="unknown",
        arguments={},
        original_content=LLMOriginalContent(provider="test", content={}),
    )

    response = await service._execute_tool(tool_call)

    assert "error" in response.response
    assert "unknown" in response.response["error"]


@pytest.mark.asyncio
async def test_execute_tool_callable_raises(make_service):
    def _bad(**kwargs):
        raise ValueError("something went wrong")

    service, _, _ = make_service(tools={"bad": {"callable": _bad, "schema": {}}})
    tool_call = LLMFunctionCall(
        name="bad",
        arguments={},
        original_content=LLMOriginalContent(provider="test", content={}),
    )

    response = await service._execute_tool(tool_call)

    assert response.response == {"error": "something went wrong"}
    assert response.call is tool_call
