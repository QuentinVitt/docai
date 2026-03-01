import hashlib
import json
import os
import os.path
import shutil
import time
from dataclasses import asdict
from logging import getLogger
from typing import Optional

from docai.llm.datatypes import (
    LLMAssistantMessage,
    LLMCacheConfig,
    LLMCacheModelConfigStrategy,
    LLMFunctionCall,
    LLMModelConfig,
    LLMOriginalContent,
    LLMProviderMessage,
    LLMRequest,
    LLMResponse,
)

logger = getLogger("docai_project")


class LRUCacheNode:
    def __init__(
        self,
        request_key,
        model_config_key,
        response,
        model_config,
    ):
        self.response = response
        self.model_config = model_config
        self.model_config_key = model_config_key
        self.request_key = request_key
        self.last_accessed = time.monotonic()  # Added for O(1) NEWEST lookup
        self.next: Optional["LRUCacheNode"] = None
        self.prev: Optional["LRUCacheNode"] = None


class LRUCache:
    CACHE_VERSION = "1.0"

    def __init__(
        self, capacity: int, model_config_strategy: LLMCacheModelConfigStrategy
    ):
        if capacity < 0:
            logger.error(
                f"The maximum LRU cache size can't be negative. max: {capacity}"
            )
            raise ValueError(
                f"The maximum LRU cache size can't be negative. max: {capacity}"
            )

        self.capacity = capacity
        self.curr_size = 0
        self.head = LRUCacheNode(None, None, None, None)
        self.tail = LRUCacheNode(None, None, None, None)
        self.head.next = self.tail
        self.tail.prev = self.head
        self.cache = {}
        self.model_config_strategy = model_config_strategy

    def _remove(self, node: LRUCacheNode):
        node.prev.next = node.next  # type: ignore
        node.next.prev = node.prev  # type: ignore

        del self.cache[node.request_key][node.model_config_key]
        if not self.cache[node.request_key]:
            del self.cache[node.request_key]

        self.curr_size -= 1

    def _add(self, node: LRUCacheNode):
        node.last_accessed = time.monotonic()  # Update time when adding/moving to front

        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node  # type: ignore
        self.head.next = node

        self.cache.setdefault(node.request_key, {})[node.model_config_key] = node
        self.curr_size += 1

    def _calculate_penalty(
        self, requested_config: LLMModelConfig, cached_config: LLMModelConfig
    ) -> float:
        penalty = 0.0

        if requested_config.name != cached_config.name:
            penalty += 1000.0

        req_gen = requested_config.generation or {}
        cache_gen = cached_config.generation or {}

        all_keys = set(req_gen.keys()) | set(cache_gen.keys())

        for key in all_keys:
            if key in req_gen and key in cache_gen:
                v1, v2 = req_gen[key], cache_gen[key]
                if type(v1) in (int, float) and type(v2) in (int, float):
                    penalty += abs(float(v1) - float(v2))
                else:
                    if v1 != v2:
                        penalty += 1.0
            else:
                penalty += 1.0

        return penalty

    def get(
        self, request_key, model_config_key, model_config
    ) -> Optional[LLMProviderMessage]:
        if request_key not in self.cache:
            return None

        node = None
        nodes_for_request = self.cache[request_key]

        match self.model_config_strategy:
            case LLMCacheModelConfigStrategy.NEWEST:
                # O(1) relative to cache size: just find max timestamp among the few nodes for this request
                node = max(nodes_for_request.values(), key=lambda n: n.last_accessed)

            case LLMCacheModelConfigStrategy.BEST_MATCH:
                node = min(
                    nodes_for_request.values(),
                    key=lambda n: self._calculate_penalty(model_config, n.model_config),
                )

            case LLMCacheModelConfigStrategy.EXACT_MATCH:
                node = nodes_for_request.get(model_config_key)

        if not node:
            return None

        # Move to front (most recently used)
        self._remove(node)
        self._add(node)
        return node.response

    def put(self, request_key, model_config_key, model_config, response) -> None:
        if model_config_key in self.cache.get(request_key, {}):
            self._remove(self.cache[request_key][model_config_key])

        node = LRUCacheNode(request_key, model_config_key, response, model_config)
        self._add(node)

        if self.curr_size > self.capacity:
            lru = self.tail.prev
            self._remove(lru)  # type: ignore


class DiskCache:
    CACHE_VERSION = "1.0"

    def __init__(
        self,
        cache_dir: str,
        start_with_clean_cache: bool,
        max_disk_size: int,
        max_age: float,
        model_config_strategy: LLMCacheModelConfigStrategy,
    ):
        self.cache_dir = cache_dir
        self.model_config_strategy = model_config_strategy

        # Check max age and size first (fast fail)
        self.max_age = max_age
        if self.max_age < 0:
            logger.error(f"The maximum file age can't be negative: {self.max_age}")
            raise ValueError(f"The maximum file age can't be negative: {self.max_age}")

        self.max_disk_size = max_disk_size
        if self.max_disk_size < 0:
            logger.error(
                f"The maximum cache size can't be negative: {self.max_disk_size}"
            )
            raise ValueError(
                f"The maximum cache size can't be negative: {self.max_disk_size}"
            )

        # Directory Setup
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        elif not os.path.isdir(self.cache_dir):
            logger.error(f"Cache directory {self.cache_dir} is not a directory")
            raise ValueError(f"Cache directory {self.cache_dir} is not a directory")

        if not os.access(self.cache_dir, os.W_OK | os.R_OK):
            logger.error(f"Cache directory {self.cache_dir} has no read/write access")
            raise ValueError(
                f"Cache directory {self.cache_dir} has no read/write access"
            )

        # Handle initialization state
        if start_with_clean_cache:
            # Wipe and bypass eviction checks
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir)
        else:
            # Only scan and evict if we are keeping old cache
            cached_files, cache_size = self._scan_cache_dir()
            cutoff_time = time.time() - self.max_age

            idx = 0

            # 1. Clean too old files
            while idx < len(cached_files) and cached_files[idx][0] < cutoff_time:
                _, old_filepath, old_size = cached_files[idx]
                self._delete_file_and_empty_dirs(old_filepath)
                cache_size -= old_size
                idx += 1

            # 2. Clean up to max_cache_size
            while idx < len(cached_files) and cache_size > self.max_disk_size:
                _, old_filepath, old_size = cached_files[idx]
                self._delete_file_and_empty_dirs(old_filepath)
                cache_size -= old_size
                idx += 1

    def _scan_cache_dir(self):
        """Single pass to get all files sorted by age and total size."""
        files = []
        total_size = 0

        for root, _, filenames in os.walk(self.cache_dir):
            for filename in filenames:
                filepath = os.path.join(root, filename)
                try:
                    mtime = os.path.getmtime(filepath)
                    size = os.path.getsize(filepath)
                    files.append((mtime, filepath, size))
                    total_size += size
                except OSError:
                    # File might have been deleted between os.walk and getmtime
                    pass

        files.sort(key=lambda x: x[0])
        return files, total_size

    def _delete_file_and_empty_dirs(self, filepath):
        """Deletes a file and removes its parent dir if it becomes empty."""
        try:
            os.remove(filepath)
            parent_dir = os.path.dirname(filepath)
            if not os.listdir(parent_dir):
                os.rmdir(parent_dir)
        except OSError as e:
            logger.warning("Failed to clean up cache file %s: %s", filepath, e)

    def _calculate_penalty(
        self, requested_config: LLMModelConfig, cached_config: LLMModelConfig
    ) -> float:
        penalty = 0.0

        if requested_config.name != cached_config.name:
            penalty += 1000.0

        req_gen = requested_config.generation or {}
        cache_gen = cached_config.generation or {}

        all_keys = set(req_gen.keys()) | set(cache_gen.keys())

        for key in all_keys:
            if key in req_gen and key in cache_gen:
                v1, v2 = req_gen[key], cache_gen[key]
                if type(v1) in (int, float) and type(v2) in (int, float):
                    penalty += abs(float(v1) - float(v2))
                else:
                    if v1 != v2:
                        penalty += 1.0
            else:
                penalty += 1.0

        return penalty

    def get(
        self, request_key: str, model_config_key: str, model_config: LLMModelConfig
    ) -> Optional[LLMProviderMessage]:
        path_to_request = os.path.join(self.cache_dir, request_key)
        if not os.path.exists(path_to_request):
            return None

        file_path = None
        match self.model_config_strategy:
            case LLMCacheModelConfigStrategy.NEWEST:
                files = os.listdir(path_to_request)
                newest_time = 0.0
                for file in files:
                    curr_file_path = os.path.join(path_to_request, file)
                    mtime = os.path.getmtime(curr_file_path)
                    if mtime > newest_time:
                        newest_time = mtime
                        file_path = curr_file_path

            case LLMCacheModelConfigStrategy.EXACT_MATCH:
                possible_file_path = os.path.join(path_to_request, model_config_key)
                if os.path.exists(possible_file_path):
                    file_path = possible_file_path

            case LLMCacheModelConfigStrategy.BEST_MATCH:
                files = os.listdir(path_to_request)
                min_penalty = float("inf")

                for file in files:
                    curr_file_path = os.path.join(path_to_request, file)
                    try:
                        with open(curr_file_path, "r") as f:
                            data = json.load(f)

                        cached_config_dict = data.get("model_config", {})
                        cached_config = LLMModelConfig(**cached_config_dict)

                        penalty = self._calculate_penalty(model_config, cached_config)
                        if penalty < min_penalty:
                            min_penalty = penalty
                            file_path = curr_file_path
                    except Exception as e:
                        logger.warning(
                            "Failed to read cache file %s for BEST_MATCH: %s",
                            curr_file_path,
                            e,
                        )

        if file_path:
            return self._read_cache_file(file_path)
        return None

    def _read_cache_file(self, file_path: str) -> LLMProviderMessage:
        """Reads the cache file and returns the JSON dictionary envelope."""
        with open(file_path, "r") as f:
            cached_envelope = json.load(f)

        msg_type = cached_envelope.get("type")
        response_data = cached_envelope.get("response", {})

        # Manually reconstruct the nested LLMOriginalContent dataclass
        if "original_content" in response_data and isinstance(
            response_data["original_content"], dict
        ):
            response_data["original_content"] = LLMOriginalContent(
                **response_data["original_content"]
            )

        match msg_type:
            case "LLMAssistantMessage":
                return LLMAssistantMessage(**response_data)
            case "LLMFunctionCall":
                return LLMFunctionCall(**response_data)
            case _:
                logger.error(
                    "Response type of file %s is not known: %s",
                    file_path,
                    msg_type,
                )
                raise ValueError(
                    f"Response type of file {file_path} is not known: {msg_type}"
                )

    def put(
        self,
        request_key: str,
        model_config_key: str,
        model_config: LLMModelConfig,
        response: LLMProviderMessage,
    ):
        response_dict = asdict(response)

        # Override the original_content with our lightweight cache indicator
        if "original_content" in response_dict:
            response_dict["original_content"] = {"provider": "cache", "content": None}

        request_cache_envelope = {
            "response": response_dict,
            "type": type(response).__name__,
            "model_config": asdict(model_config),
        }

        json_bytes = json.dumps(request_cache_envelope).encode("utf-8")
        payload_size = len(json_bytes)

        if payload_size > self.max_disk_size:
            return

        sorted_files, current_size = self._scan_cache_dir()
        cutoff_time = time.time() - self.max_age

        idx = 0
        while idx < len(sorted_files) and sorted_files[idx][0] < cutoff_time:
            _, old_filepath, old_size = sorted_files[idx]
            self._delete_file_and_empty_dirs(old_filepath)
            current_size -= old_size
            idx += 1

        while idx < len(sorted_files) and (
            current_size + payload_size > self.max_disk_size
        ):
            _, old_filepath, old_size = sorted_files[idx]
            self._delete_file_and_empty_dirs(old_filepath)
            current_size -= old_size
            idx += 1

        request_cache_path = os.path.join(self.cache_dir, request_key, model_config_key)

        os.makedirs(os.path.dirname(request_cache_path), exist_ok=True)

        with open(request_cache_path, "wb") as f:
            f.write(json_bytes)


class LLMCache:
    CACHE_VERSION = "1.0"

    def __init__(self, config: LLMCacheConfig): ...
