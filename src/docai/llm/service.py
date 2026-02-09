from docai.llm.client import LLMClient
from docai.llm.datatypes import LLMConfig


class LLMService:
    def __init__(self, config: LLMConfig):
        self._default_client = LLMClient(config.profiles.default.provider)
        self._fallback_client = LLMClient(config.profiles.fallback.provider)

        pass

    def close(self):
        self._default_client.cleanup()
        self._fallback_client.cleanup()

    def generate(self):
        pass

    def generate_batch(self):
        pass


# Now do we want to allow multiple Fallbacks or just one?
