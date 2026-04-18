from __future__ import annotations

import asyncio
from pathlib import Path

from docai.discovery.datatypes import FileClassification, FileManifest, ManifestEntry
from docai.errors import DocaiError
from docai.extractor.errors import ExtractionError
from docai.extractor.llm_fallback import extract_with_llm
from docai.llm.errors import LLMError
from docai.llm.service import LLMService
from tests.evals.framework.cases import EvalCase
from tests.evals.framework.scorer import EvalResult, score

PROJECT_ROOT: Path = Path(__file__).parent.parent.parent.parent

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python", ".go": "go", ".rs": "rust", ".java": "java",
    ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".c": "c", ".cpp": "cpp", ".h": "cpp", ".cc": "cpp",
    ".hs": "haskell", ".ex": "elixir", ".exs": "elixir",
    ".scala": "scala", ".rb": "ruby", ".pl": "prolog",
    ".scss": "scss", ".html": "html",
}


def _build_manifest(cases: list[EvalCase]) -> FileManifest:
    lang_by_fixture = {c.fixture: c.language for c in cases}
    fixtures_root = PROJECT_ROOT / "tests" / "fixtures"
    manifest: FileManifest = {}
    for f in fixtures_root.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(PROJECT_ROOT).as_posix()
        language = lang_by_fixture.get(rel) or _LANG_BY_EXT.get(f.suffix)
        manifest[rel] = ManifestEntry(
            classification=FileClassification.processed,
            language=language,
            content_hash=None,
            override=None,
        )
    return manifest


def _error_result(case: EvalCase, exc: Exception) -> EvalResult:
    msg = exc.format_compact() if isinstance(exc, DocaiError) else str(exc)
    return EvalResult(
        case=case,
        file_type_match=False,
        deps_match=False,
        pct_entities_found=0.0,
        false_entities=[],
        extra_entities=[],
        error=msg,
    )


async def run(
    cases: list[EvalCase],
    llm_service: LLMService,
    *,
    concurrency: int = 10,
) -> list[EvalResult]:
    if not cases:
        return []

    manifest = _build_manifest(cases)
    sem = asyncio.Semaphore(concurrency)

    async def _run_one(case: EvalCase) -> EvalResult:
        async with sem:
            fixture_path = PROJECT_ROOT / case.fixture
            content = fixture_path.read_text()
            manifest_entry = manifest.get(case.fixture) or ManifestEntry(
                classification=FileClassification.processed,
                language=case.language,
                content_hash=None,
                override=None,
            )
            try:
                analysis = await extract_with_llm(
                    case.fixture, content, manifest_entry, manifest, llm_service
                )
                return score(case, analysis)
            except (ExtractionError, LLMError) as exc:
                return _error_result(case, exc)

    results = await asyncio.gather(*(_run_one(c) for c in cases))
    return list(results)
