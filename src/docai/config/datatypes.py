from asyncio import Semaphore
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ---------------------------------------------------------------------------
# LLM config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMModelConfig:
    name: str
    generation: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    api_key: str


@dataclass(frozen=True)
class LLMProfileConfig:
    provider: LLMProviderConfig
    model: LLMModelConfig


@dataclass(frozen=True)
class LLMConcurrencyConfig:
    max_concurrency: int
    concurrency_semaphore: Semaphore


@dataclass(frozen=True)
class LLMRetryConfig:
    max_retries: int
    max_validation_retries: int
    retry_delay: float  # seconds
    retry_on: list[str] = field(default_factory=lambda: ["5..", "408", "429"])


class LLMCacheModelConfigStrategy(Enum):
    NEWEST = "newest"
    BEST_MATCH = "best_match"
    EXACT_MATCH = "exact_match"


@dataclass(frozen=True)
class LLMCacheConfig:
    use_cache: bool
    cache_dir: str
    start_with_clean_cache: bool = False
    max_disk_size: int = 1_000_000_000  # bytes; evicts oldest entries first
    max_age: float = 86_400  # seconds
    max_lru_size: int = 1_000
    model_config_strategy: LLMCacheModelConfigStrategy = (
        LLMCacheModelConfigStrategy.EXACT_MATCH
    )


@dataclass(frozen=True)
class LLMConfig:
    profiles: list[LLMProfileConfig]
    concurrency: LLMConcurrencyConfig
    retry: LLMRetryConfig
    cache: LLMCacheConfig
    tools: Optional[dict[str, dict]] = None


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentationCacheConfig:
    cache_dir: str
    use_cache: bool = True
    start_with_clean_cache: bool = False
    max_disk_size: int = 1_000_000_000  # bytes; evicts oldest entries first
    max_age: float = 86_400  # seconds; entries older than this are stale
    max_ram_size: Optional[int] = None  # max items in RAM cache; None = unlimited


class ProjectAction(Enum):
    DOCUMENT = "document"


@dataclass(frozen=True)
class ProjectConfig:
    action: ProjectAction
    working_dir: str  # absolute path
    documentation_cache: DocumentationCacheConfig


@dataclass(frozen=True)
class Config:
    project_config: ProjectConfig
    logging_config: dict
    llm_config: LLMConfig
