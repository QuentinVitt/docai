import time

import pytest

from docai.config.datatypes import LLMCacheModelConfigStrategy, LLMModelConfig
from docai.llm.cache import LRUCache
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMOriginalContent,
)


@pytest.fixture
def mock_response():
    def _make_response(content: str) -> LLMAssistantMessage:
        return LLMAssistantMessage(
            original_content=LLMOriginalContent(provider="test", content=content),
            content=content,
        )

    return _make_response


def test_lru_cache_negative_capacity():
    with pytest.raises(
        ValueError, match="The maximum LRU cache size can't be negative"
    ):
        LRUCache(-1, LLMCacheModelConfigStrategy.EXACT_MATCH)


def test_lru_cache_exact_match(mock_response):
    cache = LRUCache(2, LLMCacheModelConfigStrategy.EXACT_MATCH)

    config1 = LLMModelConfig(name="model-a", generation={"temp": 0.5})
    config2 = LLMModelConfig(name="model-a", generation={"temp": 0.8})

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    cache.put("req-1", "config-2", config2, mock_response("res-2"))

    assert cache.curr_size == 2

    # Test EXACT_MATCH
    res = cache.get("req-1", "config-1", config1)
    assert res is not None
    assert res.content == "res-1"  # type: ignore

    res = cache.get("req-1", "config-2", config2)
    assert res is not None
    assert res.content == "res-2"  # type: ignore

    res = cache.get("req-1", "config-3", config1)
    assert res is None


def test_lru_cache_eviction(mock_response):
    cache = LRUCache(2, LLMCacheModelConfigStrategy.EXACT_MATCH)

    config1 = LLMModelConfig(name="model-a", generation={"temp": 0.5})

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    cache.put("req-2", "config-2", config1, mock_response("res-2"))
    cache.put("req-3", "config-3", config1, mock_response("res-3"))

    assert cache.curr_size == 2

    # req-1 should be evicted
    assert cache.get("req-1", "config-1", config1) is None
    # req-2 and req-3 should remain
    assert cache.get("req-2", "config-2", config1).content == "res-2"  # type: ignore
    assert cache.get("req-3", "config-3", config1).content == "res-3"  # type: ignore


def test_lru_cache_eviction_with_access(mock_response):
    cache = LRUCache(2, LLMCacheModelConfigStrategy.EXACT_MATCH)

    config1 = LLMModelConfig(name="model-a", generation={"temp": 0.5})

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    cache.put("req-2", "config-2", config1, mock_response("res-2"))

    # Access req-1 so req-2 becomes the least recently used
    cache.get("req-1", "config-1", config1)

    # Add another one, this should evict req-2
    cache.put("req-3", "config-3", config1, mock_response("res-3"))

    assert cache.get("req-1", "config-1", config1).content == "res-1"  # type: ignore
    assert cache.get("req-2", "config-2", config1) is None
    assert cache.get("req-3", "config-3", config1).content == "res-3"  # type: ignore


def test_lru_cache_newest_strategy(mock_response):
    cache = LRUCache(3, LLMCacheModelConfigStrategy.NEWEST)

    config1 = LLMModelConfig(name="model-a", generation={"temp": 0.5})
    config2 = LLMModelConfig(name="model-a", generation={"temp": 0.8})

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    # Sleep tiny amount to ensure monotonic time changes
    time.sleep(0.01)
    cache.put("req-1", "config-2", config2, mock_response("res-2"))

    # It should return the newest one added (res-2)
    res = cache.get("req-1", "any-config-key", config1)
    assert res is not None
    assert res.content == "res-2"  # type: ignore

    # Now if we put config-1 again, its time updates and it becomes the newest
    cache.put("req-1", "config-1", config1, mock_response("res-1"))

    res = cache.get("req-1", "any-config-key", config2)
    assert res is not None
    assert res.content == "res-1"  # type: ignore


def test_lru_cache_best_match_strategy(mock_response):
    cache = LRUCache(5, LLMCacheModelConfigStrategy.BEST_MATCH)

    config1 = LLMModelConfig(name="model-a", generation={"temp": 0.5, "top_k": 50})
    config2 = LLMModelConfig(name="model-a", generation={"temp": 0.8, "top_k": 50})
    config3 = LLMModelConfig(name="model-a", generation={"temp": 0.5})
    config4 = LLMModelConfig(name="model-b", generation={"temp": 0.5})

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    cache.put("req-1", "config-2", config2, mock_response("res-2"))
    cache.put("req-1", "config-3", config3, mock_response("res-3"))
    cache.put("req-1", "config-4", config4, mock_response("res-4"))

    # 0.6 is closer to 0.5 than 0.8. Both have top_k.
    search_config1 = LLMModelConfig(
        name="model-a", generation={"temp": 0.6, "top_k": 50}
    )
    res = cache.get("req-1", "any", search_config1)
    assert res is not None
    assert res.content == "res-1"  # type: ignore

    # 0.7 is closer to 0.8 than 0.5.
    search_config2 = LLMModelConfig(
        name="model-a", generation={"temp": 0.7, "top_k": 50}
    )
    res = cache.get("req-1", "any", search_config2)
    assert res is not None
    assert res.content == "res-2"  # type: ignore

    # Exact temp, but missing top_k. It should prefer config3
    search_config3 = LLMModelConfig(name="model-a", generation={"temp": 0.5})
    res = cache.get("req-1", "any", search_config3)
    assert res is not None
    assert res.content == "res-3"  # type: ignore

    # Testing exact name matching penalty. It should pick config4
    search_config4 = LLMModelConfig(name="model-b", generation={"temp": 0.9})
    res = cache.get("req-1", "any", search_config4)
    assert res is not None
    assert res.content == "res-4"  # type: ignore


def test_lru_cache_put_overwrite(mock_response):
    cache = LRUCache(2, LLMCacheModelConfigStrategy.EXACT_MATCH)
    config = LLMModelConfig(name="model-a")

    cache.put("req-1", "config-1", config, mock_response("res-1"))
    assert cache.curr_size == 1

    # Overwrite
    cache.put("req-1", "config-1", config, mock_response("res-2"))
    assert cache.curr_size == 1

    res = cache.get("req-1", "config-1", config)
    assert res is not None
    assert res.content == "res-2"  # type: ignore
