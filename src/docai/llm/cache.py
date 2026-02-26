import hashlib
import json
from dataclasses import asdict

from docai.llm.datatypes import LLMCacheConfig, LLMModelConfig, LLMRequest


class LLMCache:
    CACHE_VERSION = "1.0"

    def __init__(self, config: LLMCacheConfig):
        self.config = config

    def _get_cache_hashes(
        self, request: LLMRequest, model_config: LLMModelConfig
    ) -> tuple[str, str]:
        """
        Generates deterministic SHA256 hashes for the request and model config.

        Returns:
            A tuple containing (request_hash, model_config_hash).
        """
        # Part 1: Generate a hash for the request's content
        request_hasher = hashlib.sha256()

        # Build a list of components to hash. Using deterministic serializers
        # like json.dumps for complex types is more robust than str().
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

        # Part 2: Generate a hash for the model configuration
        model_config_hasher = hashlib.sha256()

        # asdict converts the dataclass to a dict, and json.dumps provides
        # a stable, sorted string representation.
        serialized_model_config = json.dumps(asdict(model_config), sort_keys=True)

        model_config_hasher.update(serialized_model_config.encode("utf-8"))
        model_config_hash = model_config_hasher.hexdigest()

        return request_hash, model_config_hash
