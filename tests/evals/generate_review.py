"""
Generate pending_review.py from the latest eval results.

Usage:
    uv run python tests/evals/generate_review.py
    uv run python tests/evals/generate_review.py tests/evals/results/2026-04-15_10-30-00.json

After generating, open tests/evals/pending_review.py, remove incorrect entities,
then run:
    uv run python tests/evals/apply_review.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Resolve project root so script works from any working directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from docai.extractor.datatypes import EntityCategory  # noqa: E402
from tests.fixtures.ground_truth import GROUND_TRUTH, MustContainEntity  # noqa: E402

RESULTS_DIR = Path("tests/evals/results")
PENDING_PATH = Path("tests/evals/pending_review.py")

_CATEGORY_REPR: dict[str, str] = {
    c.value: f"EntityCategory.{c.name}" for c in EntityCategory
}


def _load_results(path: Path | None) -> tuple[dict, str, str]:
    if path is None:
        latest = RESULTS_DIR / "latest.json"
        if not latest.exists():
            print("No results found. Run evals first:")
            print("  uv run pytest tests/evals/ -m eval -v")
            sys.exit(1)
        path = latest
    data = json.loads(path.read_text())
    return data["results"], data["model"], data["timestamp"]


def _build_pending(
    results: dict, model: str, timestamp: str
) -> dict[str, list[MustContainEntity]]:
    """Return mapping of file_path → new entities not yet in ground truth."""
    pending: dict[str, list[MustContainEntity]] = {}
    for file_path, result in results.items():
        case = GROUND_TRUTH.get(file_path)
        if case is None:
            continue
        already = {(e.name, e.category) for e in case.must_contain_entities}
        new_entities = []
        for e in result.get("entities", []):
            try:
                category = EntityCategory(e["category"])
            except ValueError:
                continue
            if (e["name"], category) not in already:
                new_entities.append(
                    MustContainEntity(name=e["name"], category=category)
                )
        if new_entities:
            pending[file_path] = new_entities
    return pending


def _format_pending_py(
    pending: dict[str, list[MustContainEntity]],
    model: str,
    timestamp: str,
    source_file: str,
) -> str:
    lines = [
        '"""',
        "Pending entity review — edit this file to remove incorrect entities, then run:",
        "    uv run python tests/evals/apply_review.py",
        '"""',
        "from __future__ import annotations",
        "",
        "from docai.extractor.datatypes import EntityCategory",
        "from tests.fixtures.ground_truth import MustContainEntity as E",
        "",
        f"# Generated: {timestamp}",
        f"# Model:     {model}",
        f"# Source:    {source_file}",
        "",
        "PENDING: dict[str, list[E]] = {",
    ]

    for file_path, entities in sorted(pending.items()):
        case = GROUND_TRUTH[file_path]
        already = case.must_contain_entities
        lines.append(f'    "{file_path}": [')
        if already:
            already_strs = ", ".join(f"{e.name} ({e.category.value})" for e in already)
            lines.append(f"        # Already required: {already_strs}")
        for entity in entities:
            cat_repr = _CATEGORY_REPR.get(entity.category.value, f"EntityCategory.{entity.category.name}")
            lines.append(f"        E({entity.name!r}, {cat_repr}),")
        lines.append("    ],")

    lines += ["}", ""]
    return "\n".join(lines)


def main() -> None:
    result_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    results, model, timestamp = _load_results(result_path)
    pending = _build_pending(results, model, timestamp)

    if not pending:
        print("No new entities found — all returned entities already in ground truth.")
        return

    total_new = sum(len(v) for v in pending.values())
    source_file = str(result_path or RESULTS_DIR / "latest.json")
    content = _format_pending_py(pending, model, timestamp, source_file)
    PENDING_PATH.write_text(content)

    print(f"Written: {PENDING_PATH}")
    print(f"  {len(pending)} files with new entities, {total_new} entities total")
    print()
    print("Next steps:")
    print(f"  1. Edit {PENDING_PATH} — remove incorrect entities")
    print("  2. uv run python tests/evals/apply_review.py")


if __name__ == "__main__":
    main()
