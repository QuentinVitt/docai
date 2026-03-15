import copy

import pytest

from docai.utils import logging_utils


BASE_CONFIG = {
    "version": 1,
    "formatters": {"brief": {"format": "%(levelname)s - %(message)s"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "brief",
            "level": "DEBUG",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.FileHandler",
            "formatter": "brief",
            "level": "INFO",
            "filename": "/tmp/docai.log",
        },
    },
    "loggers": {
        "docai": {"level": "INFO", "handlers": ["console"], "propagate": False}
    },
    "root": {"level": "WARNING", "handlers": ["console"]},
}


def _capture_dictconfig(monkeypatch):
    captured = {}

    def _dictconfig(config):
        captured["config"] = config

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _dictconfig)
    return captured


def test_setup_logging_applies_config(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)

    logging_utils.setup_logging(BASE_CONFIG)

    assert captured["config"]["version"] == 1
    assert "loggers" in captured["config"]


def test_setup_logging_does_not_mutate_input_config(monkeypatch):
    def _mutating_dictconfig(config):
        config["mutated"] = True  # would affect caller without deepcopy

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _mutating_dictconfig)
    config = copy.deepcopy(BASE_CONFIG)

    logging_utils.setup_logging(config)

    assert "mutated" not in config


@pytest.mark.parametrize("exc", [ValueError("bad"), TypeError("bad"), KeyError("bad")])
def test_setup_logging_invalid_dictconfig(monkeypatch, exc):
    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _raise)
    with pytest.raises(SystemExit):
        logging_utils.setup_logging(BASE_CONFIG)


def test_setup_logging_read_only_filesystem(monkeypatch):
    captured = {}

    def _raise_read_only(*args, **kwargs):
        raise OSError(30, "Read-only file system", "/logging.log")

    def _critical(msg, *args, **kwargs):
        captured["msg"] = msg
        captured["args"] = args

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _raise_read_only)
    monkeypatch.setattr(logging_utils.logging, "critical", _critical)

    with pytest.raises(SystemExit):
        logging_utils.setup_logging(BASE_CONFIG)

    assert "can't write to log file location" in captured["msg"]
    assert captured["args"] == ("/tmp/docai.log",)


def test_setup_logging_other_oserror_is_raised(monkeypatch):
    def _raise_other(*args, **kwargs):
        raise OSError(13, "Permission denied", "/tmp/docai.log")

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _raise_other)
    with pytest.raises(OSError):
        logging_utils.setup_logging(BASE_CONFIG)


def test_setup_logging_invalid_config_shape_exits():
    with pytest.raises(SystemExit):
        logging_utils.setup_logging([])
