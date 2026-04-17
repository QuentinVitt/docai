"""
Apply approved entities from pending_review.py into ground_truth.py.

Usage:
    uv run python tests/evals/apply_review.py
    uv run python tests/evals/apply_review.py --dry-run   # print diff only
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from docai.extractor.datatypes import EntityCategory, FileType  # noqa: E402
from tests.fixtures.ground_truth import (  # noqa: E402
    GROUND_TRUTH,
    FixtureCase,
    MustContainEntity,
)

PENDING_PATH = Path("tests/evals/pending_review.py")
GROUND_TRUTH_PATH = Path("tests/fixtures/ground_truth.py")

_CATEGORY_REPR = {c: f"EntityCategory.{c.name}" for c in EntityCategory}
_FILE_TYPE_REPR = {ft: f"FileType.{ft.name}" for ft in FileType}


def _load_pending() -> dict[str, list[MustContainEntity]]:
    if not PENDING_PATH.exists():
        print(f"Not found: {PENDING_PATH}")
        print("Run generate_review.py first.")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("pending_review", PENDING_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.PENDING  # type: ignore[no-any-return]


def _merge(
    ground_truth: dict[str, FixtureCase],
    pending: dict[str, list[MustContainEntity]],
) -> dict[str, list[MustContainEntity]]:
    """Return mapping of file_path → entities actually added (net-new only)."""
    added: dict[str, list[MustContainEntity]] = {}
    for file_path, new_entities in pending.items():
        case = ground_truth.get(file_path)
        if case is None:
            print(f"  Warning: {file_path} not in GROUND_TRUTH, skipping")
            continue
        existing = {(e.name, e.category) for e in case.must_contain_entities}
        net_new = [e for e in new_entities if (e.name, e.category) not in existing]
        if net_new:
            case.must_contain_entities.extend(net_new)
            added[file_path] = net_new
    return added


def _format_entity(e: MustContainEntity) -> str:
    cat = _CATEGORY_REPR[e.category]
    return f"            E({e.name!r}, {cat}),"


def _format_case(file_path: str, case: FixtureCase) -> list[str]:
    lines = [
        f'    "{file_path}": FixtureCase(',
        f'        language={case.language!r},',
        f'        file_type={_FILE_TYPE_REPR[case.file_type]},',
    ]

    if not case.expected_deps:
        lines.append("        expected_deps=[],")
    else:
        lines.append("        expected_deps=[")
        for dep in case.expected_deps:
            lines.append(f"            {dep!r},")
        lines.append("        ],")

    if not case.must_contain_entities:
        lines.append("        must_contain_entities=[],")
    else:
        lines.append("        must_contain_entities=[")
        for e in case.must_contain_entities:
            lines.append(_format_entity(e))
        lines.append("        ],")

    lines.append("    ),")
    return lines


_SECTION_COMMENTS = {
    "tests/fixtures/source/python/exceptions.py": "# Source files — Python",
    "tests/fixtures/source/go/scanner.go": "# Source files — Go",
    "tests/fixtures/source/rust/lib.rs": "# Source files — Rust",
    "tests/fixtures/source/java/NumberUtils.java": "# Source files — Java",
    "tests/fixtures/source/javascript/chalk.js": "# Source files — JavaScript",
    "tests/fixtures/source/typescript/basic.d.ts": "# Source files — TypeScript",
    "tests/fixtures/source/c/sds.c": "# Source files — C",
    "tests/fixtures/source/cpp/Error.cpp": "# Source files — C++",
    "tests/fixtures/source/haskell/Error.hs": "# Source files — Haskell",
    "tests/fixtures/source/elixir/uri.ex": "# Source files — Elixir",
    "tests/fixtures/source/scala/Functor.scala": "# Source files — Scala",
    "tests/fixtures/source/ruby/inflections.rb": "# Source files — Ruby",
    "tests/fixtures/source/prolog/simple.pl": "# Source files — Prolog",
    "tests/fixtures/source_like_config/styles.scss": "# Source-like config — SCSS / Makefile / HTML templates",
    "tests/fixtures/config/config.yaml": "# Config files — no deps, no entities",
}


def _generate_ground_truth_py(ground_truth: dict[str, FixtureCase]) -> str:
    lines = [
        '"""',
        "Ground truth for fixture files used in extractor eval tests.",
        "",
        "Each entry defines:",
        "- language: for ManifestEntry construction",
        "- file_type: expected FileType classification",
        "- expected_deps: exact list of paths the LLM must return as dependencies",
        "  ([] for standalone source files; specific paths for source_like_config)",
        "- must_contain_entities: subset of entities that MUST appear in the result",
        "  (name + category exact match; order irrelevant)",
        '"""',
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass, field",
        "",
        "from docai.extractor.datatypes import EntityCategory, FileType",
        "",
        "",
        "@dataclass(frozen=True)",
        "class MustContainEntity:",
        "    name: str",
        "    category: EntityCategory",
        "",
        "",
        "@dataclass",
        "class FixtureCase:",
        "    language: str",
        "    file_type: FileType",
        "    expected_deps: list[str]",
        "    must_contain_entities: list[MustContainEntity] = field(default_factory=list)",
        "",
        "",
        "E = MustContainEntity  # shorthand",
        "",
        "# ---------------------------------------------------------------------------",
        "# Source files — Python",
        "# ---------------------------------------------------------------------------",
        "",
        "GROUND_TRUTH: dict[str, FixtureCase] = {",
    ]

    first = True
    for file_path, case in ground_truth.items():
        comment = _SECTION_COMMENTS.get(file_path)
        if comment and not first:
            lines.append("")
            lines.append("    # " + "-" * 75)
            lines.append(f"    # {comment}")
            lines.append("    # " + "-" * 75)
            lines.append("")
        first = False
        lines.extend(_format_case(file_path, case))

    lines += ["}", ""]
    return "\n".join(lines)


def main(dry_run: bool = False) -> None:
    pending = _load_pending()
    added = _merge(GROUND_TRUTH, pending)

    if not added:
        print("Nothing to apply — no net-new entities in pending_review.py.")
        return

    total = sum(len(v) for v in added.values())
    print(f"Applying {total} new entities across {len(added)} files:")
    for file_path, entities in added.items():
        print(f"  {Path(file_path).name}: +{len(entities)}")
        for e in entities:
            print(f"    + {e.name} ({e.category.value})")

    if dry_run:
        print("\n(dry-run — no files written)")
        return

    content = _generate_ground_truth_py(GROUND_TRUTH)
    GROUND_TRUTH_PATH.write_text(content)
    print(f"\nUpdated: {GROUND_TRUTH_PATH}")
    print("Delete pending_review.py when done:")
    print(f"  rm {PENDING_PATH}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
