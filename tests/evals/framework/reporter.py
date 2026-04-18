from __future__ import annotations

import json
from pathlib import Path

from tests.evals.framework.scorer import EvalResult


def print_results(results: list[EvalResult]) -> None:
    if not results:
        print("0 cases run.")
        return

    for r in results:
        name = r.case.id.split("__")[-1]
        type_mark = "✓ type" if r.file_type_match else "✗ type"
        deps_mark = "✓ deps" if r.deps_match else "✗ deps"
        if r.error:
            line = f"  {name:<30}  ERROR: {r.error}"
        else:
            line = (
                f"  {name:<30}  {r.pct_entities_found:5.1f}% entities"
                f"  |  {len(r.false_entities)} false"
                f"  |  {len(r.extra_entities)} extra"
                f"  |  {type_mark}"
                f"  |  {deps_mark}"
            )
        print(line)

    passed = sum(
        1 for r in results
        if r.file_type_match and r.deps_match and r.pct_entities_found == 100.0 and not r.error
    )
    avg = sum(r.pct_entities_found for r in results) / len(results)
    print(f"\n{passed}/{len(results)} cases fully passed, {avg:.1f}% avg entities found")


def save_results(results: list[EvalResult], run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "case_id": r.case.id,
            "fixture": r.case.fixture,
            "file_type_match": r.file_type_match,
            "deps_match": r.deps_match,
            "pct_entities_found": r.pct_entities_found,
            "false_entities": [{"name": e.name, "category": e.category.value} for e in r.false_entities],
            "extra_entities": [{"name": e.name, "category": e.category.value} for e in r.extra_entities],
            "error": r.error,
        }
        for r in results
    ]
    (run_dir / "summary.json").write_text(json.dumps(data, indent=2))
