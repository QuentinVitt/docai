import io
import os
from types import SimpleNamespace

import pytest
import yaml

from docai.config import loader


def test_load_config_file_success(monkeypatch):
    monkeypatch.setattr(
        loader.resources,
        "open_text",
        lambda *args, **kwargs: io.StringIO("a: 1\n"),
    )

    config = loader.load_config_file("docai.config", "dummy.yaml")

    assert config == {"a": 1}


def test_load_config_file_missing(monkeypatch):
    def _raise_missing(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(loader.resources, "open_text", _raise_missing)

    with pytest.raises(loader.ConfigError, match="not found"):
        loader.load_config_file("docai.config", "missing.yaml")


def test_load_config_file_yaml_error(monkeypatch):
    monkeypatch.setattr(
        loader.resources,
        "open_text",
        lambda *args, **kwargs: io.StringIO("a: 1\n"),
    )

    def _raise_yaml(*args, **kwargs):
        raise yaml.YAMLError("bad yaml")

    monkeypatch.setattr(loader.yaml, "safe_load", _raise_yaml)

    with pytest.raises(loader.ConfigError, match="Invalid configuration file"):
        loader.load_config_file("docai.config", "bad.yaml")


def test_load_config_file_invalid_shape(monkeypatch):
    monkeypatch.setattr(
        loader.resources,
        "open_text",
        lambda *args, **kwargs: io.StringIO("a: 1\n"),
    )
    monkeypatch.setattr(loader.yaml, "safe_load", lambda *args, **kwargs: [])

    with pytest.raises(loader.ConfigError, match="YAML mapping"):
        loader.load_config_file("docai.config", "shape.yaml")


def test_build_project_args_uses_directory(tmp_path):
    args = SimpleNamespace(directory=str(tmp_path), action="document", interactive=False)

    project_args = loader.build_project_args(args)

    assert project_args.working_dir == os.path.abspath(str(tmp_path))
    assert project_args.action == "document"
    assert project_args.interactive is False


def test_build_project_args_uses_cwd(monkeypatch):
    monkeypatch.setattr(loader.os, "getcwd", lambda: "/tmp/work")
    args = SimpleNamespace(directory=None, action="document", interactive=True)

    project_args = loader.build_project_args(args)

    assert project_args.working_dir == "/tmp/work"
    assert project_args.interactive is True


def test_build_project_args_oserror(monkeypatch):
    def _raise_oserror():
        raise OSError("bad cwd")

    monkeypatch.setattr(loader.os, "getcwd", _raise_oserror)
    args = SimpleNamespace(directory=None, action="document", interactive=False)

    with pytest.raises(loader.ConfigError, match="Error identifying working directory"):
        loader.build_project_args(args)


def test_load_config_combines_parts(monkeypatch):
    cli_args = SimpleNamespace(directory=None, action="document", interactive=False)
    project_args = loader.ProjectArgs(
        action="document", working_dir="/tmp/work", interactive=False
    )
    calls = []

    def _load_config_file(package, filename):
        calls.append((package, filename))
        return {"file": filename}

    monkeypatch.setattr(loader, "parse_arguments", lambda: cli_args)
    monkeypatch.setattr(loader, "build_project_args", lambda args: project_args)
    monkeypatch.setattr(loader, "load_config_file", _load_config_file)

    config = loader.load_config()

    assert config.cli_args is cli_args
    assert config.project_args is project_args
    assert config.logger_args == {"file": loader.LOG_CONFIG_FILE}
    assert config.llm_args == {"file": loader.LLM_CONFIG_FILE}
    assert calls == [
        (loader.LOG_CONFIG_PACKAGE, loader.LOG_CONFIG_FILE),
        (loader.LLM_CONFIG_PACKAGE, loader.LLM_CONFIG_FILE),
    ]
