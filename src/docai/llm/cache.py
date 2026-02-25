from docai.llm.datatypes import LLMCacheConfig, LLMModelConfig, LLMRequest


class LLMCache:
    def __init__(self, config: LLMCacheConfig): ...

    def _get_key(self, request: LLMRequest, model_config: LLMModelConfig):

        # request key:
        # - prompt
        # - system_prompt
        # - history
        # - structured_output
        # - allowed_tools
        # Dividing sequence: $$$

        request_key = f"({request.prompt}"
        ...
