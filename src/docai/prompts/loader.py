from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from docai.prompts.errors import PromptNotFoundError

PROMPTS_ROOT: Path = Path(__file__).parent / "templates"

logger = logging.getLogger(__name__)


@dataclass
class PromptTemplate:
    system_prompt_template: str
    user_prompt_template: str


def load_prompt(area: str, language: str | None = None) -> PromptTemplate:
    base_path = PROMPTS_ROOT / area / "base.yaml"
    if not base_path.exists():
        raise PromptNotFoundError(
            message=f"No base prompt found for area '{area}'",
            code="PROMPT_NOT_FOUND",
        )

    base_data = yaml.safe_load(base_path.read_text())
    base = PromptTemplate(
        system_prompt_template=base_data["system_prompt_template"],
        user_prompt_template=base_data["user_prompt_template"],
    )

    if language is None:
        return base

    overrides_dir = PROMPTS_ROOT / area / "overrides"
    if not overrides_dir.is_dir():
        return base

    matched: PromptTemplate | None = None
    for override_file in sorted(overrides_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(override_file.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or data.get("language") != language:
            continue
        if matched is not None:
            logger.warning(
                "Duplicate override for language '%s' in area '%s', using '%s'",
                language,
                area,
                override_file.name,
            )
            continue
        matched = PromptTemplate(
            system_prompt_template=data["system_prompt_template"],
            user_prompt_template=data["user_prompt_template"],
        )

    return matched if matched is not None else base
