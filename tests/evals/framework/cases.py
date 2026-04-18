from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CASES_ROOT: Path = Path(__file__).parent.parent / "cases"


@dataclass(frozen=True)
class CaseEntity:
    name: str
    category: str


@dataclass
class EvalCase:
    id: str
    fixture: str
    language: str
    file_type: str
    expected_deps: list[str]
    must_contain: list[CaseEntity]
    should_not_contain: list[CaseEntity]
    tags: list[str]
    area: str


def _derive_id(rel_path: Path) -> str:
    stem = rel_path.with_suffix("").as_posix()
    return stem.replace("/", "__").replace(".", "_")


def _parse_entities(raw: list[dict]) -> list[CaseEntity]:
    return [CaseEntity(name=e["name"], category=e["category"]) for e in raw]


def _parse_case(data: dict, area: str, rel_path: Path) -> EvalCase:
    return EvalCase(
        id=_derive_id(rel_path),
        fixture=data["fixture"],
        language=data["language"],
        file_type=data["file_type"],
        expected_deps=data["expected_deps"],
        must_contain=_parse_entities(data["must_contain"]),
        should_not_contain=_parse_entities(data.get("should_not_contain", [])),
        tags=data.get("tags", []),
        area=area,
    )


def load_cases(
    area: str,
    ids: list[str] | None = None,
    *,
    cases_root: Path = CASES_ROOT,
) -> list[EvalCase]:
    area_dir = cases_root / area
    if not area_dir.is_dir():
        return []

    cases: list[EvalCase] = []
    for yaml_file in sorted(area_dir.rglob("*.yaml")):
        rel_path = yaml_file.relative_to(area_dir)
        try:
            data = yaml.safe_load(yaml_file.read_text())
            if not isinstance(data, dict):
                continue
            case = _parse_case(data, area, rel_path)
        except (yaml.YAMLError, KeyError, TypeError):
            continue
        if ids is None or case.id in ids:
            cases.append(case)

    cases.sort(key=lambda c: c.id)
    return cases
