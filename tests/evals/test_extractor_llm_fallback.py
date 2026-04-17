"""
Eval tests for extract_with_llm — real API calls against fixture files.

Run with:
    uv run pytest tests/evals/ -m eval -v

Override model:
    DOCAI_EVAL_MODEL=gemini/gemini-2-flash-preview GEMINI_API_KEY=... uv run pytest tests/evals/ -m eval -v

Results saved to tests/evals/results/ after each run.
Review new entities with:
    uv run python tests/evals/generate_review.py
"""
from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from docai.discovery.datatypes import FileClassification, FileManifest, ManifestEntry
from docai.extractor.datatypes import FileType
from docai.extractor.llm_fallback import extract_with_llm
from docai.llm.datatypes import LLMProfile, LogConfig, ModelConfig
from docai.llm.service import LLMService
from tests.fixtures.ground_truth import GROUND_TRUTH, FixtureCase

FIXTURES_ROOT = Path("tests/fixtures")
RESULTS_DIR = Path("tests/evals/results")

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "cpp",
    ".cc": "cpp",
    ".hs": "haskell",
    ".ex": "elixir",
    ".exs": "elixir",
    ".scala": "scala",
    ".rb": "ruby",
    ".pl": "prolog",
    ".scss": "scss",
    ".mk": "makefile",
    ".html": "jinja2",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".env": "dotenv",
}

_LANG_BY_NAME: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
}


def _guess_language(path: str) -> str:
    p = Path(path)
    if p.name in _LANG_BY_NAME:
        return _LANG_BY_NAME[p.name]
    return _LANG_BY_EXT.get(p.suffix, "unknown")


def _build_full_manifest() -> FileManifest:
    """Build a manifest of all fixture files for use as the file_manifest arg."""
    manifest: FileManifest = {}
    for path in FIXTURES_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        path_str = str(path)
        lang = (
            GROUND_TRUTH[path_str].language
            if path_str in GROUND_TRUTH
            else _guess_language(path_str)
        )
        manifest[path_str] = ManifestEntry(
            classification=FileClassification.processed,
            language=lang,
            content_hash="eval-fixture",
            override=None,
        )
    return manifest


def _save_results(collected: dict, model: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    payload = {"timestamp": ts, "model": model, "results": collected}
    data = json.dumps(payload, indent=2)
    (RESULTS_DIR / f"{ts}.json").write_text(data)
    (RESULTS_DIR / "latest.json").write_text(data)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def eval_model() -> str:
    return os.environ.get("DOCAI_EVAL_MODEL", "claude-haiku-4-5-20251001")


@pytest.fixture(scope="session")
def llm_service(
    tmp_path_factory: pytest.TempPathFactory,
    eval_model: str,
) -> LLMService:
    log_dir = tmp_path_factory.mktemp("eval_llm_logs")
    profile = LLMProfile(models=[ModelConfig(model=eval_model, num_retries=3)])
    return LLMService(profile=profile, log_config=LogConfig(log_dir=log_dir))


@pytest.fixture(scope="session")
def file_manifest() -> FileManifest:
    return _build_full_manifest()


@pytest.fixture(scope="session")
def results_collector(eval_model: str) -> Generator[dict, None, None]:
    collected: dict = {}
    yield collected
    if collected:
        _save_results(collected, eval_model)


# ---------------------------------------------------------------------------
# Parametrized eval test
# ---------------------------------------------------------------------------


@pytest.mark.eval
@pytest.mark.parametrize(
    "file_path,case",
    list(GROUND_TRUTH.items()),
    ids=[Path(k).name for k in GROUND_TRUTH],
)
async def test_extract_with_llm(
    file_path: str,
    case: FixtureCase,
    llm_service: LLMService,
    file_manifest: FileManifest,
    results_collector: dict,
) -> None:
    content = Path(file_path).read_text()
    manifest_entry = file_manifest[file_path]

    result = await extract_with_llm(
        file_path=file_path,
        content=content,
        manifest_entry=manifest_entry,
        file_manifest=file_manifest,
        llm_service=llm_service,
    )

    # Save before assertions — captures results even when a test fails
    results_collector[file_path] = {
        "file_type": result.file_type.value,
        "dependencies": result.dependencies,
        "entities": [
            {
                "name": e.name,
                "category": e.category.value,
                "kind": e.kind,
                "parent": e.parent,
                "signature": e.signature,
            }
            for e in result.entities
        ],
    }

    # --- FileType ---
    assert result.file_type == case.file_type, (
        f"file_type wrong.\n"
        f"  expected: {case.file_type}\n"
        f"  got:      {result.file_type}"
    )

    # --- Dependencies ---
    assert sorted(result.dependencies) == sorted(case.expected_deps), (
        f"dependencies wrong.\n"
        f"  expected: {sorted(case.expected_deps)}\n"
        f"  got:      {sorted(result.dependencies)}"
    )

    # --- Entities: non-source_file must have empty list ---
    if case.file_type != FileType.source_file:
        assert result.entities == [], (
            f"entities must be empty for {case.file_type}, got: {result.entities}"
        )

    # --- Entities: must_contain_entities subset check ---
    if case.must_contain_entities:
        found = {(e.name, e.category) for e in result.entities}
        missing = [
            e for e in case.must_contain_entities
            if (e.name, e.category) not in found
        ]
        assert not missing, (
            f"missing expected entities: {[(e.name, e.category) for e in missing]}\n"
            f"found: {sorted((e.name, str(e.category)) for e in result.entities)}"
        )
