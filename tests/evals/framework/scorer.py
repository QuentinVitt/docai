from __future__ import annotations

from dataclasses import dataclass, field

from docai.extractor.datatypes import Entity, FileAnalysis
from tests.evals.framework.cases import CaseEntity, EvalCase


@dataclass
class EvalResult:
    case: EvalCase
    file_type_match: bool
    deps_match: bool
    pct_entities_found: float
    false_entities: list[Entity]
    extra_entities: list[Entity]
    error: str | None = None


def score(case: EvalCase, actual: FileAnalysis) -> EvalResult:
    file_type_match = actual.file_type.value == case.file_type
    deps_match = sorted(actual.dependencies) == sorted(case.expected_deps)

    must_keys = {(e.name, e.category) for e in case.must_contain}
    should_not_keys = {(e.name, e.category) for e in case.should_not_contain}
    actual_keys = {(e.name, e.category.value) for e in actual.entities}

    found = sum(1 for k in must_keys if k in actual_keys)
    pct_entities_found = (found / len(must_keys) * 100.0) if must_keys else 100.0

    false_entities = [e for e in actual.entities if (e.name, e.category.value) in should_not_keys]
    extra_entities = [
        e for e in actual.entities
        if (e.name, e.category.value) not in must_keys
        and (e.name, e.category.value) not in should_not_keys
    ]

    return EvalResult(
        case=case,
        file_type_match=file_type_match,
        deps_match=deps_match,
        pct_entities_found=pct_entities_found,
        false_entities=false_entities,
        extra_entities=extra_entities,
    )
