from __future__ import annotations

import logging
from pathlib import Path

import pytest

from docai.prompts.errors import PromptNotFoundError
from docai.prompts.loader import PromptTemplate, load_prompt

_BASE_SYSTEM = "You are a code expert."
_BASE_USER = "Analyze {content}."
_OVERRIDE_SYSTEM = "You are a Python expert."
_OVERRIDE_USER = "Analyze this Python code: {content}."


def _write_base(root: Path, area: str = "extractor") -> None:
    d = root / area
    d.mkdir(parents=True, exist_ok=True)
    (d / "base.yaml").write_text(
        f"system_prompt_template: {_BASE_SYSTEM!r}\n"
        f"user_prompt_template: {_BASE_USER!r}\n"
    )


def _write_override(root: Path, language: str, filename: str, area: str = "extractor") -> None:
    d = root / area / "overrides"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(
        f"language: {language}\n"
        f"system_prompt_template: {_OVERRIDE_SYSTEM!r}\n"
        f"user_prompt_template: {_OVERRIDE_USER!r}\n"
    )


# ── happy path ────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestHappyPath:
    def test_no_language_returns_base_templates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        result = load_prompt("extractor", language=None)
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER

    def test_language_given_no_overrides_dir_returns_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        result = load_prompt("extractor", language="python")
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER

    def test_matching_override_returns_override_templates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        _write_override(tmp_path, language="python", filename="python.yaml")
        result = load_prompt("extractor", language="python")
        assert result.system_prompt_template == _OVERRIDE_SYSTEM
        assert result.user_prompt_template == _OVERRIDE_USER

    def test_no_matching_override_returns_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        _write_override(tmp_path, language="go", filename="go.yaml")
        result = load_prompt("extractor", language="python")
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER

    def test_language_none_with_overrides_present_returns_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        _write_override(tmp_path, language="python", filename="python.yaml")
        result = load_prompt("extractor", language=None)
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER

    def test_override_dir_empty_returns_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        (tmp_path / "extractor" / "overrides").mkdir(parents=True)
        result = load_prompt("extractor", language="python")
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER

    def test_returns_prompt_template_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        result = load_prompt("extractor")
        assert isinstance(result, PromptTemplate)
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER


# ── error cases ───────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestErrorCases:
    def test_missing_base_yaml_raises_prompt_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        (tmp_path / "extractor").mkdir()
        with pytest.raises(PromptNotFoundError) as exc_info:
            load_prompt("extractor")
        assert exc_info.value.code == "PROMPT_NOT_FOUND"

    def test_missing_base_yaml_error_message_includes_area(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        (tmp_path / "extractor").mkdir()
        with pytest.raises(PromptNotFoundError) as exc_info:
            load_prompt("extractor")
        assert exc_info.value.message == "No base prompt found for area 'extractor'"


# ── edge cases ────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEdgeCases:
    def test_malformed_override_yaml_skipped_returns_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        d = tmp_path / "extractor" / "overrides"
        d.mkdir(parents=True)
        (d / "python.yaml").write_text(":: invalid: yaml: [[[")
        result = load_prompt("extractor", language="python")
        assert result.system_prompt_template == _BASE_SYSTEM
        assert result.user_prompt_template == _BASE_USER

    def test_duplicate_language_uses_first_alphabetically_and_logs_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("docai.prompts.loader.PROMPTS_ROOT", tmp_path)
        _write_base(tmp_path)
        d = tmp_path / "extractor" / "overrides"
        d.mkdir(parents=True)
        (d / "aaa_python.yaml").write_text(
            "language: python\n"
            "system_prompt_template: 'first'\n"
            "user_prompt_template: 'first user'\n"
        )
        (d / "zzz_python.yaml").write_text(
            "language: python\n"
            "system_prompt_template: 'second'\n"
            "user_prompt_template: 'second user'\n"
        )
        with caplog.at_level(logging.WARNING, logger="docai.prompts.loader"):
            result = load_prompt("extractor", language="python")
        assert result.system_prompt_template == "first"
        assert result.user_prompt_template == "first user"
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
