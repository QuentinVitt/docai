"""One-time migration: converts GROUND_TRUTH dict to YAML eval cases."""
from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
CASES_ROOT = PROJECT_ROOT / "tests" / "evals" / "cases" / "extractor"


def _yaml_path(fixture_path: str) -> Path:
    p = Path(fixture_path)
    rel = p.relative_to("tests/fixtures")
    safe_name = p.name.replace(".", "_")
    if p.name.startswith("."):
        safe_name = safe_name.lstrip("_")
    yaml_name = safe_name + ".yaml"
    return CASES_ROOT / rel.parent / yaml_name


def main() -> None:
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    sys.path.insert(0, str(PROJECT_ROOT))

    from tests.fixtures.ground_truth import GROUND_TRUTH

    written = 0
    for fixture_path, case in GROUND_TRUTH.items():
        out_path = _yaml_path(fixture_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        entities = [
            {"name": e.name, "category": e.category.value}
            for e in case.must_contain_entities
        ]

        data = {
            "fixture": fixture_path,
            "language": case.language,
            "file_type": case.file_type.value,
            "expected_deps": case.expected_deps,
            "must_contain": entities,
            "should_not_contain": [],
            "tags": [case.language],
        }

        out_path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        written += 1
        print(f"  wrote {out_path.relative_to(PROJECT_ROOT)}")

    print(f"\n{written} YAML files written to {CASES_ROOT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
