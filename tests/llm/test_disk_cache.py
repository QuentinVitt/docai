import json
import os
import shutil
import time

import pytest

from docai.llm.cache import DiskCache, LLMCacheModelConfigStrategy
from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMModelConfig,
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


@pytest.fixture
def temp_cache_dir(tmp_path):
    return str(tmp_path / "cache_dir")


def test_disk_cache_negative_age(temp_cache_dir):
    with pytest.raises(ValueError, match="The maximum file age can't be negative"):
        DiskCache(
            cache_dir=temp_cache_dir,
            start_with_clean_cache=False,
            max_disk_size=1000,
            max_age=-1,
            model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
        )


def test_disk_cache_negative_size(temp_cache_dir):
    with pytest.raises(ValueError, match="The maximum cache size can't be negative"):
        DiskCache(
            cache_dir=temp_cache_dir,
            start_with_clean_cache=False,
            max_disk_size=-1,
            max_age=1000,
            model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
        )


def test_disk_cache_put_and_exact_match(temp_cache_dir, mock_response):
    cache = DiskCache(
        cache_dir=temp_cache_dir,
        start_with_clean_cache=True,
        max_disk_size=1000000,
        max_age=1000,
        model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
    )

    config = LLMModelConfig(name="model-a", generation={"temp": 0.5})
    msg = mock_response("res-1")

    cache.put("req-1", "config-1", config, msg)

    res = cache.get("req-1", "config-1", config)
    assert res is not None
    assert res.content == "res-1"


def test_disk_cache_strips_original_content(temp_cache_dir, mock_response):
    cache = DiskCache(
        cache_dir=temp_cache_dir,
        start_with_clean_cache=True,
        max_disk_size=1000000,
        max_age=1000,
        model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
    )

    config = LLMModelConfig(name="model-a")
    msg = mock_response("res-1")

    cache.put("req-1", "config-1", config, msg)

    # Check file contents to see if stripped
    file_path = os.path.join(temp_cache_dir, "req-1", "config-1")
    with open(file_path, "r") as f:
        data = json.load(f)

    assert data["response"]["original_content"]["provider"] == "cache"
    assert data["response"]["original_content"]["content"] is None

    # Retrieve and check
    res = cache.get("req-1", "config-1", config)
    assert res is not None
    assert res.original_content.provider == "cache"
    assert res.original_content.content is None


def test_disk_cache_newest_strategy(temp_cache_dir, mock_response):
    cache = DiskCache(
        cache_dir=temp_cache_dir,
        start_with_clean_cache=True,
        max_disk_size=1000000,
        max_age=1000,
        model_config_strategy=LLMCacheModelConfigStrategy.NEWEST,
    )

    config1 = LLMModelConfig(name="model-a")
    config2 = LLMModelConfig(name="model-b")

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    time.sleep(0.01)
    cache.put("req-1", "config-2", config2, mock_response("res-2"))

    res = cache.get("req-1", "any", config1)
    assert res is not None
    assert res.content == "res-2"


def test_disk_cache_best_match_strategy(temp_cache_dir, mock_response):
    cache = DiskCache(
        cache_dir=temp_cache_dir,
        start_with_clean_cache=True,
        max_disk_size=1000000,
        max_age=1000,
        model_config_strategy=LLMCacheModelConfigStrategy.BEST_MATCH,
    )

    config1 = LLMModelConfig(name="model-a", generation={"temp": 0.5})
    config2 = LLMModelConfig(name="model-a", generation={"temp": 0.8})

    cache.put("req-1", "config-1", config1, mock_response("res-1"))
    cache.put("req-1", "config-2", config2, mock_response("res-2"))

    search_config1 = LLMModelConfig(name="model-a", generation={"temp": 0.6})
    res = cache.get("req-1", "any", search_config1)
    assert res is not None
    assert res.content == "res-1"

    search_config2 = LLMModelConfig(name="model-a", generation={"temp": 0.9})
    res = cache.get("req-1", "any", search_config2)
    assert res is not None
    assert res.content == "res-2"


def test_disk_cache_eviction_by_size(temp_cache_dir, mock_response):
    # Small disk size to force eviction
    cache = DiskCache(
        cache_dir=temp_cache_dir,
        start_with_clean_cache=True,
        max_disk_size=250,  # Needs to be small enough to evict first response but large enough to hold at least one
        max_age=1000,
        model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
    )

    config = LLMModelConfig(name="model-a")
    cache.put("req-1", "config-1", config, mock_response("a" * 10))
    time.sleep(0.01)
    cache.put("req-2", "config-2", config, mock_response("b" * 10))

    # Give it a moment or ensure the sizes correctly triggered eviction
    # The JSON envelope size needs to exceed max_disk_size together, but individually be smaller.

    # Actually wait, we should check if they were evicted.
    # The cache put logic evicts when current_size + payload_size > max_disk_size
    # Let's see if req-1 is None
    assert cache.get("req-1", "config-1", config) is None
    assert cache.get("req-2", "config-2", config) is not None


def test_disk_cache_eviction_by_age(temp_cache_dir, mock_response):
    cache = DiskCache(
        cache_dir=temp_cache_dir,
        start_with_clean_cache=True,
        max_disk_size=100000,
        max_age=0.05,  # Extremely short age
        model_config_strategy=LLMCacheModelConfigStrategy.EXACT_MATCH,
    )

    config = LLMModelConfig(name="model-a")
    cache.put("req-1", "config-1", config, mock_response("res-1"))

    # Wait for the file to become too old
    time.sleep(0.1)

    # Trigger an init to perform eviction, or put
    cache.put("req-2", "config-2", config, mock_response("res-2"))

    # Now req-1 should be evicted from disk
    assert cache.get("req-1", "config-1", config) is None
    assert cache.get("req-2", "config-2", config) is not None
