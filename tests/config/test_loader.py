import io
import os
import sys
from types import SimpleNamespace

import pytest
import yaml

from docai.config import datatypes as dt
from docai.config import loader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["docai", *args])
    return loader.parse_arguments()


def _make_args(**kwargs):
    defaults = dict(
        directory=".",
        action="document",
        verbose=False,
        quiet=False,
        silent=False,
        llm_profile="default",
        no_cache=False,
        new_cache=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _valid_llm_yaml(
    profile_name="default",
    api_key=None,
    api_key_env="GEMINI_API_KEY",
    max_concurrent_requests=5,
):
    provider_entry = {}
    if api_key is not None:
        provider_entry["api_key"] = api_key
    else:
        provider_entry["api_key_env"] = api_key_env

    config = {
        "providers": {"google": provider_entry},
        "models": {"gemini-2.5-flash": {"name": "gemini-2.5-flash"}},
        "profiles": {
            profile_name: [{"provider": "google", "model": "gemini-2.5-flash"}]
        },
        "globals": {"max_concurrent_requests": max_concurrent_requests},
        "retry": {"max_retries": 2, "retry_delay": 500, "retry_on": ["5xx", "429"]},
        "cache": {
            "cache_dir": ".docai/cache/llm",
            "max_disk_size": 500_000,
            "max_age": 3600,
            "max_lru_size": 100,
            "model_config_strategy": "newest",
        },
    }
    return yaml.dump(config)


def _patch_llm_yaml(monkeypatch, yaml_str):
    monkeypatch.setattr(
        loader.resources,
        "open_text",
        lambda *a, **kw: io.StringIO(yaml_str),
    )


def _patch_log_yaml(monkeypatch, yaml_str=None):
    if yaml_str is None:
        yaml_str = yaml.dump(
            {"loggers": {"docai": {"level": "INFO", "handlers": [], "propagate": False}}}
        )
    monkeypatch.setattr(
        loader.resources,
        "open_text",
        lambda *a, **kw: io.StringIO(yaml_str),
    )


# ---------------------------------------------------------------------------
# parse_arguments
# ---------------------------------------------------------------------------


def test_parse_document_defaults(monkeypatch):
    args = _parse(monkeypatch, "document")
    assert args.action == "document"
    assert args.directory == "."
    assert args.llm_profile == "default"
    assert args.no_cache is False
    assert args.new_cache is False
    assert args.verbose is False
    assert args.quiet is False
    assert args.silent is False


def test_parse_document_custom_directory(monkeypatch):
    args = _parse(monkeypatch, "document", "/tmp/project")
    assert args.directory == "/tmp/project"


def test_parse_document_llm_profile(monkeypatch):
    args = _parse(monkeypatch, "document", "--llm-profile", "fast")
    assert args.llm_profile == "fast"


def test_parse_document_llm_profile_short(monkeypatch):
    args = _parse(monkeypatch, "document", "-lp", "fast")
    assert args.llm_profile == "fast"


def test_parse_document_llm_profile_is_string_not_list(monkeypatch):
    # nargs=1 would return a list; ensure it's a plain string
    args = _parse(monkeypatch, "document", "-lp", "fast")
    assert isinstance(args.llm_profile, str)


def test_parse_document_no_cache(monkeypatch):
    args = _parse(monkeypatch, "document", "--no-cache")
    assert args.no_cache is True
    assert args.new_cache is False


def test_parse_document_new_cache(monkeypatch):
    args = _parse(monkeypatch, "document", "--new-cache")
    assert args.new_cache is True
    assert args.no_cache is False


def test_parse_document_cache_flags_mutually_exclusive(monkeypatch):
    with pytest.raises(SystemExit):
        _parse(monkeypatch, "document", "--no-cache", "--new-cache")


@pytest.mark.parametrize("flag,attr", [("-v", "verbose"), ("-q", "quiet"), ("-s", "silent")])
def test_parse_document_verbosity_flags(monkeypatch, flag, attr):
    args = _parse(monkeypatch, "document", flag)
    assert getattr(args, attr) is True
    other = {"verbose", "quiet", "silent"} - {attr}
    for o in other:
        assert getattr(args, o) is False


@pytest.mark.parametrize("flags", [("-v", "-q"), ("-v", "-s"), ("-q", "-s")])
def test_parse_document_verbosity_mutually_exclusive(monkeypatch, flags):
    with pytest.raises(SystemExit):
        _parse(monkeypatch, "document", *flags)


def test_parse_no_subcommand_fails(monkeypatch):
    with pytest.raises(SystemExit):
        _parse(monkeypatch)


# ---------------------------------------------------------------------------
# build_project_config
# ---------------------------------------------------------------------------


def test_build_project_config_absolute_path(tmp_path):
    args = _make_args(directory=str(tmp_path))
    config = loader.build_project_config(args)
    assert config.working_dir == str(tmp_path)
    assert config.action == dt.ProjectAction.DOCUMENT


def test_build_project_config_relative_path(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.os, "getcwd", lambda: str(tmp_path))
    args = _make_args(directory=".")
    config = loader.build_project_config(args)
    assert config.working_dir == str(tmp_path)


def test_build_project_config_returns_enum(tmp_path):
    args = _make_args(directory=str(tmp_path), action="document")
    config = loader.build_project_config(args)
    assert isinstance(config.action, dt.ProjectAction)


def test_build_project_config_not_a_directory(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    args = _make_args(directory=str(f))
    with pytest.raises(loader.ConfigError, match="Not a directory"):
        loader.build_project_config(args)


def test_build_project_config_nonexistent_path():
    args = _make_args(directory="/nonexistent/path/xyz")
    with pytest.raises(loader.ConfigError, match="Not a directory"):
        loader.build_project_config(args)


def test_build_project_config_no_access(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.os, "access", lambda *a, **kw: False)
    args = _make_args(directory=str(tmp_path))
    with pytest.raises(loader.ConfigError, match="Cannot read/write"):
        loader.build_project_config(args)


def test_build_project_config_invalid_action(tmp_path):
    args = _make_args(directory=str(tmp_path), action="nonexistent")
    with pytest.raises(loader.ConfigError, match="Unknown action"):
        loader.build_project_config(args)


def test_build_project_config_oserror(monkeypatch):
    monkeypatch.setattr(loader.os.path, "isabs", lambda p: False)
    monkeypatch.setattr(loader.os, "getcwd", lambda: (_ for _ in ()).throw(OSError("bad")))
    args = _make_args(directory="relative")
    with pytest.raises(loader.ConfigError, match="Error identifying working directory"):
        loader.build_project_config(args)


# ---------------------------------------------------------------------------
# build_logger_config
# ---------------------------------------------------------------------------


_BASE_LOG_CONFIG = {
    "loggers": {"docai": {"level": "INFO", "handlers": [], "propagate": False}}
}


@pytest.fixture
def patch_log_yaml(monkeypatch):
    def _patch(cfg=None):
        yaml_str = yaml.dump(cfg or _BASE_LOG_CONFIG)
        monkeypatch.setattr(
            loader.resources,
            "open_text",
            lambda *a, **kw: io.StringIO(yaml_str),
        )

    return _patch


def test_build_logger_config_default_level(patch_log_yaml):
    patch_log_yaml()
    args = _make_args(verbose=False, quiet=False, silent=False)
    config = loader.build_logger_config(args)
    assert config["loggers"]["docai"]["level"] == "INFO"


def test_build_logger_config_verbose(patch_log_yaml):
    patch_log_yaml()
    config = loader.build_logger_config(_make_args(verbose=True))
    assert config["loggers"]["docai"]["level"] == "DEBUG"


def test_build_logger_config_quiet(patch_log_yaml):
    patch_log_yaml()
    config = loader.build_logger_config(_make_args(quiet=True))
    assert config["loggers"]["docai"]["level"] == "ERROR"


def test_build_logger_config_silent(patch_log_yaml):
    patch_log_yaml()
    config = loader.build_logger_config(_make_args(silent=True))
    assert config["loggers"]["docai"]["level"] == "CRITICAL"


def test_build_logger_config_missing_file(monkeypatch):
    monkeypatch.setattr(
        loader.resources, "open_text", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError())
    )
    with pytest.raises(loader.ConfigError, match="not found"):
        loader.build_logger_config(_make_args())


def test_build_logger_config_invalid_yaml(monkeypatch):
    monkeypatch.setattr(loader.resources, "open_text", lambda *a, **kw: io.StringIO("a: 1"))
    monkeypatch.setattr(loader.yaml, "safe_load", lambda _: (_ for _ in ()).throw(yaml.YAMLError()))
    with pytest.raises(loader.ConfigError, match="Invalid configuration file"):
        loader.build_logger_config(_make_args())


def test_build_logger_config_non_dict_yaml(monkeypatch):
    monkeypatch.setattr(loader.resources, "open_text", lambda *a, **kw: io.StringIO("- a"))
    monkeypatch.setattr(loader.yaml, "safe_load", lambda _: ["a"])
    with pytest.raises(loader.ConfigError, match="YAML mapping"):
        loader.build_logger_config(_make_args())


def test_build_logger_config_missing_docai_logger(monkeypatch):
    bad = {"loggers": {"other": {}}}
    monkeypatch.setattr(
        loader.resources, "open_text", lambda *a, **kw: io.StringIO(yaml.dump(bad))
    )
    with pytest.raises(loader.ConfigError, match="'docai' logger"):
        loader.build_logger_config(_make_args(verbose=True))


# ---------------------------------------------------------------------------
# build_llm_config
# ---------------------------------------------------------------------------


def test_build_llm_config_returns_llm_config(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="test-key"))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert isinstance(result, dt.LLMConfig)


def test_build_llm_config_profiles_built(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="test-key"))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert len(result.profiles) == 1
    assert result.profiles[0].model.name == "gemini-2.5-flash"
    assert result.profiles[0].provider.name == "google"
    assert result.profiles[0].provider.api_key == "test-key"


def test_build_llm_config_fallback_profiles(monkeypatch, tmp_path):
    config = yaml.safe_load(_valid_llm_yaml(api_key="key"))
    config["models"]["gemini-1.5-pro"] = {"name": "gemini-1.5-pro"}
    config["profiles"]["default"].append({"provider": "google", "model": "gemini-1.5-pro"})
    _patch_llm_yaml(monkeypatch, yaml.dump(config))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert len(result.profiles) == 2


def test_build_llm_config_api_key_env(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key_env="MY_KEY"))
    monkeypatch.setenv("MY_KEY", "env-api-key")
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert result.profiles[0].provider.api_key == "env-api-key"


def test_build_llm_config_api_key_env_missing(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key_env="MISSING_KEY"))
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(loader.ConfigError, match="MISSING_KEY"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_provider_no_key(monkeypatch, tmp_path):
    config = yaml.safe_load(_valid_llm_yaml())
    del config["providers"]["google"]["api_key_env"]
    _patch_llm_yaml(monkeypatch, yaml.dump(config))
    with pytest.raises(loader.ConfigError, match="api_key.*api_key_env"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_use_cache_from_no_cache_flag(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    result = loader.build_llm_config(_make_args(no_cache=True), str(tmp_path))
    assert result.cache.use_cache is False


def test_build_llm_config_use_cache_default(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    result = loader.build_llm_config(_make_args(no_cache=False), str(tmp_path))
    assert result.cache.use_cache is True


def test_build_llm_config_start_with_clean_cache(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    result = loader.build_llm_config(_make_args(new_cache=True), str(tmp_path))
    assert result.cache.start_with_clean_cache is True


def test_build_llm_config_cache_dir_is_absolute(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert os.path.isabs(result.cache.cache_dir)
    assert result.cache.cache_dir == str(tmp_path / ".docai" / "cache" / "llm")


def test_build_llm_config_retry_from_retry_section(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert result.retry.max_retries == 2
    assert result.retry.retry_delay == 0.5


def test_build_llm_config_concurrency_from_globals(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k", max_concurrent_requests=7))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert result.concurrency.max_concurrency == 7


def test_build_llm_config_tools_registry_present(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    result = loader.build_llm_config(_make_args(), str(tmp_path))
    assert result.tools is not None
    assert "get_file_tree" in result.tools
    assert "read_file" in result.tools


@pytest.mark.parametrize("missing", ["profiles", "models", "providers", "globals"])
def test_build_llm_config_missing_required_section(monkeypatch, tmp_path, missing):
    config = yaml.safe_load(_valid_llm_yaml(api_key="k"))
    del config[missing]
    _patch_llm_yaml(monkeypatch, yaml.dump(config))
    with pytest.raises(loader.ConfigError, match=f"'{missing}'"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_profile_not_found(monkeypatch, tmp_path):
    _patch_llm_yaml(monkeypatch, _valid_llm_yaml(api_key="k"))
    with pytest.raises(loader.ConfigError, match="not found"):
        loader.build_llm_config(_make_args(llm_profile="nonexistent"), str(tmp_path))


def test_build_llm_config_profile_not_a_list(monkeypatch, tmp_path):
    config = yaml.safe_load(_valid_llm_yaml(api_key="k"))
    config["profiles"]["default"] = {"provider": "google", "model": "gemini-2.5-flash"}
    _patch_llm_yaml(monkeypatch, yaml.dump(config))
    with pytest.raises(loader.ConfigError, match="invalid configuration"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_model_not_found(monkeypatch, tmp_path):
    config = yaml.safe_load(_valid_llm_yaml(api_key="k"))
    config["profiles"]["default"][0]["model"] = "nonexistent-model"
    _patch_llm_yaml(monkeypatch, yaml.dump(config))
    with pytest.raises(loader.ConfigError, match="invalid configuration"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_provider_not_found(monkeypatch, tmp_path):
    config = yaml.safe_load(_valid_llm_yaml(api_key="k"))
    config["profiles"]["default"][0]["provider"] = "nonexistent-provider"
    _patch_llm_yaml(monkeypatch, yaml.dump(config))
    with pytest.raises(loader.ConfigError, match="invalid configuration"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        loader.resources, "open_text", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError())
    )
    with pytest.raises(loader.ConfigError, match="not found"):
        loader.build_llm_config(_make_args(), str(tmp_path))


def test_build_llm_config_invalid_yaml(monkeypatch, tmp_path):
    monkeypatch.setattr(loader.resources, "open_text", lambda *a, **kw: io.StringIO("a: 1"))
    monkeypatch.setattr(loader.yaml, "safe_load", lambda _: (_ for _ in ()).throw(yaml.YAMLError()))
    with pytest.raises(loader.ConfigError, match="Invalid configuration file"):
        loader.build_llm_config(_make_args(), str(tmp_path))
