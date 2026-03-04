import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMModelConfig,
    LLMOriginalContent,
    LLMRequest,
    LLMResponse,
    LLMRetryConfig,
    LLMUserMessage,
)
from docai.llm.errors import LLMError
from docai.llm.runner import _run, _status_code_matches, run


@pytest.fixture
def mock_request():
    return LLMRequest(prompt=LLMUserMessage(content="test prompt"), id=uuid.uuid4())


@pytest.fixture
def mock_model_config():
    return LLMModelConfig(name="test-model")


@pytest.fixture
def mock_response():
    msg = LLMAssistantMessage(
        original_content=LLMOriginalContent(provider="test", content=""),
        content="success",
    )
    return LLMResponse(response=msg, id=uuid.uuid4())


@pytest.fixture
def retry_policy():
    return LLMRetryConfig(max_retries=3, retry_delay=1, retry_on=["5xx", "408"])


# --- Tests for _status_code_matches ---


def test_status_code_matches():
    # 5xx pattern tests
    assert _status_code_matches(["5xx"], 500) is True
    assert _status_code_matches(["5xx"], 503) is True
    assert _status_code_matches(["5xx"], 599) is True
    assert _status_code_matches(["5XX"], 502) is True
    assert _status_code_matches(["5xx"], 400) is False
    assert _status_code_matches(["5xx"], 5000) is False

    # exact match
    assert _status_code_matches(["408"], 408) is True
    assert _status_code_matches(["408"], 409) is False

    # dot notation regex
    assert _status_code_matches(["5.."], 500) is True
    assert _status_code_matches(["5.."], 499) is False

    # Multiple patterns
    assert _status_code_matches(["5xx", "429"], 429) is True
    assert _status_code_matches(["5xx", "429"], 502) is True
    assert _status_code_matches(["5xx", "429"], 404) is False


# --- Tests for _run ---


@pytest.mark.asyncio
async def test_run_internal_success(
    mock_request, mock_model_config, mock_response, retry_policy
):
    client = MagicMock()
    client.generate = AsyncMock(return_value=mock_response)
    semaphore = asyncio.Semaphore(1)

    result = await _run(
        client, mock_request, mock_model_config, retry_policy, semaphore
    )

    assert result == mock_response
    client.generate.assert_called_once_with(mock_request, mock_model_config)


@pytest.mark.asyncio
@patch("docai.llm.runner.asyncio.sleep", new_callable=AsyncMock)
async def test_run_internal_retry_on_llmerror(
    mock_sleep, mock_request, mock_model_config, mock_response, retry_policy
):
    client = MagicMock()
    # Fail once with 500, succeed on second try
    client.generate = AsyncMock(
        side_effect=[LLMError(status_code=500, response="Server error"), mock_response]
    )
    semaphore = asyncio.Semaphore(1)

    result = await _run(
        client, mock_request, mock_model_config, retry_policy, semaphore
    )

    assert result == mock_response
    assert client.generate.call_count == 2
    mock_sleep.assert_called_once()
    # Sleep arg should be approx 1 * (2**0) + jitter (0-1) = 1 to 2
    sleep_time = mock_sleep.call_args[0][0]
    assert 1.0 <= sleep_time <= 2.0


@pytest.mark.asyncio
async def test_run_internal_no_retry_on_unmatched_llmerror(
    mock_request, mock_model_config, retry_policy
):
    client = MagicMock()
    # Fail with 400, which is not in retry_on
    client.generate = AsyncMock(
        side_effect=LLMError(status_code=400, response="Bad request")
    )
    semaphore = asyncio.Semaphore(1)

    with pytest.raises(LLMError) as exc_info:
        await _run(client, mock_request, mock_model_config, retry_policy, semaphore)

    assert exc_info.value.status_code == 400
    assert client.generate.call_count == 1


@pytest.mark.asyncio
@patch("docai.llm.runner.asyncio.sleep", new_callable=AsyncMock)
async def test_run_internal_retry_on_generic_exception(
    mock_sleep, mock_request, mock_model_config, mock_response, retry_policy
):
    client = MagicMock()
    # Fail once with generic Exception, succeed on second try
    client.generate = AsyncMock(
        side_effect=[Exception("Network dropped"), mock_response]
    )
    semaphore = asyncio.Semaphore(1)

    result = await _run(
        client, mock_request, mock_model_config, retry_policy, semaphore
    )

    assert result == mock_response
    assert client.generate.call_count == 2
    mock_sleep.assert_called_once()


@pytest.mark.asyncio
@patch("docai.llm.runner.asyncio.sleep", new_callable=AsyncMock)
async def test_run_internal_max_retries_exceeded(
    mock_sleep, mock_request, mock_model_config, retry_policy
):
    client = MagicMock()
    # Always fail
    client.generate = AsyncMock(
        side_effect=LLMError(status_code=503, response="Unavailable")
    )
    semaphore = asyncio.Semaphore(1)

    with pytest.raises(LLMError) as exc_info:
        await _run(client, mock_request, mock_model_config, retry_policy, semaphore)

    assert exc_info.value.status_code == 611
    assert "All tries failed" in exc_info.value.response  # type: ignore
    assert client.generate.call_count == 3
    assert mock_sleep.call_count == 3

    # Check backoff timing
    sleep1 = mock_sleep.call_args_list[0][0][0]
    sleep2 = mock_sleep.call_args_list[1][0][0]
    sleep3 = mock_sleep.call_args_list[2][0][0]

    assert 1.0 <= sleep1 <= 2.0
    assert 2.0 <= sleep2 <= 3.0
    assert 4.0 <= sleep3 <= 5.0


@pytest.mark.asyncio
@patch("docai.llm.runner.random.uniform", return_value=0.0)
@patch("docai.llm.runner.asyncio.sleep", new_callable=AsyncMock)
async def test_run_internal_exponential_backoff(
    mock_sleep, mock_random, mock_request, mock_model_config
):
    client = MagicMock()
    # Always fail to trigger all retries
    client.generate = AsyncMock(
        side_effect=LLMError(status_code=503, response="Unavailable")
    )
    # Configure a custom policy with 5 retries and 2s base delay
    policy = LLMRetryConfig(max_retries=5, retry_delay=2, retry_on=["5xx"])
    semaphore = asyncio.Semaphore(1)

    with pytest.raises(LLMError):
        await _run(client, mock_request, mock_model_config, policy, semaphore)

    assert mock_sleep.call_count == 5

    # Calculate exact expected delays: base_delay * (2^t)
    # 2 * 1 = 2, 2 * 2 = 4, 2 * 4 = 8, 2 * 8 = 16, 2 * 16 = 32
    expected_sleeps = [2.0, 4.0, 8.0, 16.0, 32.0]
    actual_sleeps = [call.args[0] for call in mock_sleep.call_args_list]

    assert actual_sleeps == expected_sleeps


# --- Tests for run (Orchestrator) ---


@pytest.mark.asyncio
async def test_run_cache_hit(
    mock_request, mock_model_config, mock_response, retry_policy
):
    cache = MagicMock()
    cache.get.return_value = mock_response  # Cache hit
    client = MagicMock()
    client.generate = AsyncMock()
    semaphore = asyncio.Semaphore(1)

    result = await run(
        cache, mock_request, mock_model_config, client, retry_policy, semaphore
    )

    assert result == mock_response
    cache.get.assert_called_once_with(mock_request, mock_model_config)
    cache.put.assert_not_called()
    client.generate.assert_not_called()


@pytest.mark.asyncio
@patch("docai.llm.runner._run", new_callable=AsyncMock)
async def test_run_cache_miss(
    mock_internal_run, mock_request, mock_model_config, mock_response, retry_policy
):
    cache = MagicMock()
    cache.get.return_value = None  # Cache miss
    client = MagicMock()
    semaphore = asyncio.Semaphore(1)

    mock_internal_run.return_value = mock_response

    result = await run(
        cache, mock_request, mock_model_config, client, retry_policy, semaphore
    )

    assert result == mock_response
    cache.get.assert_called_once_with(mock_request, mock_model_config)
    mock_internal_run.assert_called_once_with(
        client, mock_request, mock_model_config, retry_policy, semaphore
    )
    cache.put.assert_called_once_with(mock_request, mock_model_config, mock_response)
