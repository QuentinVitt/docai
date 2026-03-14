import uuid

import pytest

from docai.config.datatypes import (
    LLMCacheConfig,
    LLMCacheModelConfigStrategy,
    LLMModelConfig,
)
from docai.llm.cache import LLMCache
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMOriginalContent,
    LLMRequest,
    LLMResponse,
    LLMUserMessage,
)


@pytest.fixture
def mock_config(tmp_path):
    return LLMCacheConfig(
        use_cache=True,
        cache_dir=str(tmp_path / "llm_cache"),
        start_with_clean_cache=True,
        max_disk_size=1000000,
        max_age=1000,
        max_lru_size=10,
        model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
    )


@pytest.fixture
def mock_request():
    return LLMRequest(prompt=LLMUserMessage(content="Hello"), id=uuid.uuid4())


@pytest.fixture
def mock_response():
    provider_msg = LLMAssistantMessage(
        original_content=LLMOriginalContent(provider="test", content="Hi there"),
        content="Hi there",
    )
    return LLMResponse(response=provider_msg, id=uuid.uuid4())


@pytest.fixture
def mock_model_config():
    return LLMModelConfig(name="test-model")


def test_llm_cache_disabled(
    mock_config, mock_request, mock_response, mock_model_config
):
    config = LLMCacheConfig(
        use_cache=False,
        cache_dir=mock_config.cache_dir,
        max_disk_size=1000,
        max_age=1000,
        max_lru_size=10,
        model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
    )
    cache = LLMCache(config)

    # Put shouldn't do anything because use_cache is False
    cache.put(mock_request, mock_model_config, mock_response)

    # Get should return None immediately
    assert cache.get(mock_request, mock_model_config) is None


def test_llm_cache_put_and_get(
    mock_config, mock_request, mock_response, mock_model_config
):
    cache = LLMCache(mock_config)

    # Put response
    cache.put(mock_request, mock_model_config, mock_response)

    # Get response should hit LRU cache (and return correct dataclass)
    res = cache.get(mock_request, mock_model_config)
    assert res is not None
    assert res.response.content == "Hi there"  # type: ignore
    assert res.id == mock_request.id


def test_llm_cache_read_through(
    mock_config, mock_request, mock_response, mock_model_config
):
    cache = LLMCache(mock_config)

    # Manually put directly into the disk cache, bypassing LRU memory
    request_hash, model_config_hash = cache._get_cache_hashes(
        mock_request, mock_model_config
    )
    cache.disk_cache.put(
        request_hash, model_config_hash, mock_model_config, mock_response.response
    )

    # Verify LRU cache is completely empty
    assert cache.lru_cache.curr_size == 0

    # First get triggers disk read and populates LRU memory
    res = cache.get(mock_request, mock_model_config)
    assert res is not None
    assert res.response.content == "Hi there"  # type: ignore

    # Verify it was successfully written back to LRU memory for next time
    assert cache.lru_cache.curr_size == 1


def test_llm_cache_hashes_deterministic():
    cache = LLMCache(
        LLMCacheConfig(
            use_cache=True,
            cache_dir="/tmp/test_dir",
            max_disk_size=1000,
            max_age=100,
            max_lru_size=10,
        )
    )

    # Exact identical requests
    req1 = LLMRequest(prompt=LLMUserMessage(content="Hello"))
    req2 = LLMRequest(prompt=LLMUserMessage(content="Hello"))

    # Different request
    req3 = LLMRequest(prompt=LLMUserMessage(content="Different"))

    # Exact identical configs
    config1 = LLMModelConfig(name="test")
    config2 = LLMModelConfig(name="test")

    # Different config
    config3 = LLMModelConfig(name="test2")

    req1_hash, conf1_hash = cache._get_cache_hashes(req1, config1)
    req2_hash, conf2_hash = cache._get_cache_hashes(req2, config2)
    req3_hash, conf3_hash = cache._get_cache_hashes(req3, config3)

    # Same inputs should yield exact same hashes
    assert req1_hash == req2_hash
    assert conf1_hash == conf2_hash

    # Different inputs should yield different hashes
    assert req1_hash != req3_hash
    assert conf1_hash != conf3_hash


def test_llm_cache_hashes_handles_history_and_tools():
    cache = LLMCache(
        LLMCacheConfig(
            use_cache=True,
            cache_dir="/tmp/test_dir",
            max_disk_size=1000,
            max_age=100,
            max_lru_size=10,
        )
    )

    config = LLMModelConfig(name="test")

    req1 = LLMRequest(
        prompt=LLMUserMessage(content="Hello"),
        history=[
            LLMAssistantMessage(
                content="History", original_content=LLMOriginalContent("test", "test")
            )
        ],
        allowed_tools={"tool_b", "tool_a"},  # Set order doesn't matter
    )

    req2 = LLMRequest(
        prompt=LLMUserMessage(content="Hello"),
        history=[
            LLMAssistantMessage(
                content="History", original_content=LLMOriginalContent("test", "test")
            )
        ],
        allowed_tools={"tool_a", "tool_b"},  # Same tools, different order
    )

    req3 = LLMRequest(
        prompt=LLMUserMessage(content="Hello"),
        history=[],  # Different history
        allowed_tools={"tool_a", "tool_b"},
    )

    req1_hash, _ = cache._get_cache_hashes(req1, config)
    req2_hash, _ = cache._get_cache_hashes(req2, config)
    req3_hash, _ = cache._get_cache_hashes(req3, config)

    assert req1_hash == req2_hash  # Tool set sorting makes hashes deterministic
    assert req1_hash != req3_hash  # History change should alter hash


def test_llm_cache_miss(mock_config, mock_request, mock_model_config):
    cache = LLMCache(mock_config)
    assert cache.get(mock_request, mock_model_config) is None
