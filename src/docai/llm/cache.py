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
    LLMCacheConfig,
    LLMCacheModelConfigStrategy,
    LLMModelConfig,
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


class DiskCache: ...


class LLMCache:
    CACHE_VERSION = "1.0"

    def __init__(self, config: LLMCacheConfig):
        self._config = config

        # Check if cache_dir is correctly set up
        if not os.path.exists(self._config.cache_dir):
            os.makedirs(self._config.cache_dir)

        if not os.path.isdir(self._config.cache_dir):
            logger.error(
                "Cache directory %s is not a directory", self._config.cache_dir
            )
            raise ValueError(
                "Cache directory %s is not a directory", self._config.cache_dir
            )

        if not os.access(self._config.cache_dir, os.W_OK | os.R_OK):
            logger.error(
                "Cache directory %s has no read/write access", self._config.cache_dir
            )
            raise ValueError(
                "Cache directory %s has no read/write access", self._config.cache_dir
            )

        # Clean complete cache if start_with_clean_cache is set
        if self._config.start_with_clean_cache:
            shutil.rmtree(self._config.cache_dir)
            os.makedirs(self._config.cache_dir)

        # Check if max_age is correctly set up
        if self._config.max_age < 0:
            logger.error(
                "The maximum file age can't be negative. max file age: %s",
                self._config.max_age,
            )
            raise ValueError(
                "The maximum file age can't be negative. max file age: %s"
                % self._config.max_age
            )

        cached_files, cache_size = self._scan_cache_dir()

        # Clean cache of too old files
        cutoff_time = time.time() - self._config.max_age

        while cached_files and cached_files[0][0] < cutoff_time:
            _, old_filepath, old_size = cached_files.pop(0)
            self._delete_file_and_empty_dirs(old_filepath)
            cache_size -= old_size

        # Check if max_cache_size is correctly set up
        if self._config.max_disk_size < 0:
            logger.error(
                "The maximum cache size can't be negative. max cache size: %s",
                self._config.max_disk_size,
            )
            raise ValueError(
                "The maximum cache size can't be negative. max cache size: %s"
                % self._config.max_disk_size
            )

        # Clean up cache to max_cache_size
        while cached_files and (cache_size > self._config.max_disk_size):
            _, old_filepath, old_size = cached_files.pop(0)
            self._delete_file_and_empty_dirs(old_filepath)
            cache_size -= old_size

        # Set up datastruct for lru cache
        self._lru_head, self._lru_tail = None, None
        self._lru_dict = {}

    def set(
        self,
        request: LLMRequest,
        model_config: LLMModelConfig,
        response: LLMResponse,
    ):
        if not self._config.use_cache:
            return

        # 1. Prepare the payload and calculate its size
        request_hash, model_config_hash = self._get_cache_hashes(request, model_config)

        # set lru cache
        if self._lru_dict.get(request_hash, {}).get(model_config_hash, None):
            lru_cache_node = self._lru_dict[request_hash][model_config_hash]
            lru_cache_node.prev.next = lru_cache_node.next
            lru_cache_node.next.prev = lru_cache_node.prev

        new_lru_cache_node = LRUCacheNode(
            request_hash, model_config_hash, response.response, model_config
        )
        new_lru_cache_node.next = self._lru_head
        new_lru_cache_node.prev = self._lru_head.prev  # type: ignore
        self._lru_head.prev.next = new_lru_cache_node  # type: ignore
        self._lru_head.prev = new_lru_cache_node  # type: ignore

        self._lru_dict[request_hash] = self._lru_dict.get(request_hash, {})[
            model_config_hash
        ] = new_lru_cache_node

        request_cache_envelope = {
            "response": asdict(response.response),
            "type": type(response.response).__name__,
            "model_config": asdict(model_config),
        }

        # set lru cache

        # Serialize once, use the bytes for length and writing
        json_bytes = json.dumps(request_cache_envelope).encode("utf-8")
        payload_size = len(json_bytes)

        # Abort if the single payload is larger than the max cache size
        if payload_size > self._config.max_disk_size:
            logger.warning("Response too large to cache")
            return

        # 2. Scan the current cache state
        sorted_files, current_size = self._scan_cache_dir()

        # 3. Time-based eviction (Delete files older than max_age)
        # Assuming max_age is in seconds.
        cutoff_time = time.time() - self._config.max_age

        # Iterate through a copy or pop from the original list
        while sorted_files and sorted_files[0][0] < cutoff_time:
            _, old_filepath, old_size = sorted_files.pop(0)
            self._delete_file_and_empty_dirs(old_filepath)
            current_size -= old_size

        # 4. Size-based eviction (Make room for the new payload)
        max_size = self._config.max_disk_size
        while sorted_files and (current_size + payload_size > max_size):
            # pop(0) ensures we remove the OLDEST file
            _, old_filepath, old_size = sorted_files.pop(0)
            self._delete_file_and_empty_dirs(old_filepath)
            current_size -= old_size

        # 5. Write the new cache file
        request_cache_path = os.path.join(
            self._config.cache_dir, request_hash, model_config_hash
        )

        # Only create the parent directory (request_hash)
        os.makedirs(os.path.dirname(request_cache_path), exist_ok=True)

        # Write the pre-serialized bytes directly
        with open(request_cache_path, "wb") as f:
            f.write(json_bytes)

    # def get(
    #     self, request: LLMRequest, model_config: LLMModelConfig
    # ) -> Optional[LLMProviderMessage]:

    #     if not os.path.isdir(self._config.use_cache):
    #         logger.error(
    #             "Cache directory is not a directory %s", self._config.use_cache
    #         )
    #         raise ValueError(
    #             "Cache directory is not a directory %s", self._config.use_cache
    #         )

    #     request_hash, model_config_hash = self._get_cache_hashes(request, model_config)
    #     request_path = os.path.join(self._config.cache_dir, request_hash)

    #     if not os.path.exists(request_path):
    #         return None

    #     if not os.path.isdir(request_path):
    #         logger.error(
    #             "cache directory for the request is not a directory %s", request_path
    #         )
    #         raise ValueError(
    #             "cache directory for the request is not a directory %s", request_path
    #         )

    #     match self._config.model_config_strategy:
    #         case LLMCacheModelConfigStrategy.NEWEST:
    #             return self._get_newest(request_path)
    #         case LLMCacheModelConfigStrategy.BEST_MATCH:
    #             return self._get_best_match(request_hash)
    #         case LLMCacheModelConfigStrategy.EXACT_MATCH:
    #             return self._get_exact_match(request_hash, model_config_hash)
    #         case _:
    #             return None

    def _get_cache_hashes(
        self, request: LLMRequest, model_config: LLMModelConfig
    ) -> tuple[str, str]:
        """
        Generates deterministic SHA256 hashes for the request and model config.

        Returns:
            A tuple containing (request_hash, model_config_hash).
        """
        # Generate a hash for the request's content
        request_hasher = hashlib.sha256()

        request_components = [
            str(request.prompt),
            str(request.system_prompt or ""),
            " $ ".join(map(str, request.history)),
            json.dumps(request.structured_output, sort_keys=True)
            if request.structured_output
            else None,
            ",".join(sorted(request.allowed_tools)) if request.allowed_tools else None,
        ]

        for component in request_components:
            request_hasher.update(component.encode("utf-8"))

        request_hash = request_hasher.hexdigest()

        # Generate a hash for the model configuration
        model_config_hasher = hashlib.sha256()
        serialized_model_config = json.dumps(asdict(model_config), sort_keys=True)

        model_config_hasher.update(serialized_model_config.encode("utf-8"))
        model_config_hash = model_config_hasher.hexdigest()

        return request_hash, model_config_hash

    def _scan_cache_dir(self):
        """Single pass to get all files sorted by age and total size."""
        files = []
        total_size = 0

        for root, _, filenames in os.walk(self._config.cache_dir):
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

    # def _get_newest(self, request_path) -> Optional[LLMProviderMessage]:
    #     # open the file in this directory with the newest timestamp
    #     files = os.listdir(request_path)
    #     last_modified_time, last_modified_file = float("inf"), None
    #     for file in files:
    #         file_path = os.path.join(request_path, file)
    #         last_modified = os.path.getmtime(file_path)
    #         if last_modified < last_modified_time:
    #             last_modified_time = last_modified
    #             last_modified_file = file_path

    #     return self._read_cache_file(last_modified_file) if last_modified_file else None

    # def _get_exact_match(
    #     self, request_path, model_config_hash
    # ) -> Optional[LLMProviderMessage]:
    #     full_path = os.path.join(request_path, model_config_hash)

    #     if os.path.exists(full_path) and os.path.isfile(full_path):
    #         return self._read_cache_file(full_path)

    #     return None

    # def _get_best_match(self, request_hash) -> Optional[LLMProviderMessage]: ...

    # def _read_cache_file(self, file_path) -> LLMProviderMessage: ...

    # def _clean_old_entries(self, dir: Optional[str] = None):
    #     if dir is None:
    #         dir = self._config.cache_dir

    #     for p in os.listdir(dir):
    #         if os.path.isdir(os.path.join(dir, p)):
    #             self._clean_old_entries(os.path.join(dir, p))
    #         elif (
    #             os.path.isfile(os.path.join(dir, p))
    #             and os.path.getmtime(os.path.join(dir, p)) >= self._config.max_age
    #         ):
    #             os.remove(os.path.join(dir, p))
