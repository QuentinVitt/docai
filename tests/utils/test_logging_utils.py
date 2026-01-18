import logging
import os
from types import SimpleNamespace

import pytest
import yaml

from docai.utils import logging_utils


BASE_CONFIG = """
version: 1
formatters:
  brief:
    format: "%(levelname)s - %(message)s"
handlers:
  console:
    class: logging.StreamHandler
    formatter: brief
    level: DEBUG
    stream: ext://sys.stdout
  file:
    class: logging.FileHandler
    formatter: brief
    level: INFO
    filename: /tmp/docai.log
loggers:
  docai_project:
    level: INFO
    handlers: [console]
    propagate: False
root:
  level: WARNING
  handlers: [console]
"""

ROTATING_CONFIG = """
version: 1
formatters:
  brief:
    format: "%(levelname)s - %(message)s"
handlers:
  console:
    class: logging.StreamHandler
    formatter: brief
    level: DEBUG
    stream: ext://sys.stdout
  file:
    class: logging.handlers.RotatingFileHandler
    formatter: brief
    level: INFO
    filename: /tmp/docai.log
    maxBytes: 100
    backupCount: 2
loggers:
  docai_project:
    level: INFO
    handlers: [console]
    propagate: False
root:
  level: WARNING
  handlers: [console]
"""


def _make_args(**overrides):
    defaults = dict(
        verbose=False,
        quiet=False,
        silent=False,
        log=False,
        log_level=None,
        log_file=None,
        log_max_size=None,
        log_backup_count=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_logger_args(config_text=BASE_CONFIG):
    return yaml.safe_load(config_text)


def _capture_dictconfig(monkeypatch):
    captured = {}

    def _dictconfig(config):
        captured["config"] = config

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _dictconfig)
    return captured


@pytest.mark.parametrize(
    "arg_name, expected_level",
    [
        ("verbose", logging.DEBUG),
        ("quiet", logging.WARNING),
        ("silent", logging.CRITICAL),
    ],
)
def test_setup_logging_sets_logger_level(monkeypatch, arg_name, expected_level):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(**{arg_name: True})

    logging_utils.setup_logging(args, _make_logger_args())

    logger_config = captured["config"]["loggers"][logging_utils.LOGGER_KEY]
    assert logger_config["level"] == expected_level


def test_setup_logging_verbose_takes_precedence(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(verbose=True, quiet=True, silent=True)

    logging_utils.setup_logging(args, _make_logger_args())

    logger_config = captured["config"]["loggers"][logging_utils.LOGGER_KEY]
    assert logger_config["level"] == logging.DEBUG


def test_setup_logging_quiet_takes_precedence_over_silent(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(quiet=True, silent=True)

    logging_utils.setup_logging(args, _make_logger_args())

    logger_config = captured["config"]["loggers"][logging_utils.LOGGER_KEY]
    assert logger_config["level"] == logging.WARNING


def test_setup_logging_defaults_preserved(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args()

    logging_utils.setup_logging(args, _make_logger_args())

    logger_config = captured["config"]["loggers"][logging_utils.LOGGER_KEY]
    assert logger_config["level"] == "INFO"
    assert logger_config["handlers"] == ["console"]


def test_setup_logging_enables_file_handler(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(log=True)

    logging_utils.setup_logging(args, _make_logger_args())

    handlers = captured["config"]["loggers"][logging_utils.LOGGER_KEY]["handlers"]
    assert "file" in handlers


def test_setup_logging_does_not_duplicate_file_handler(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    logger_args = _make_logger_args()
    logger_args["loggers"][logging_utils.LOGGER_KEY]["handlers"].append("file")

    logging_utils.setup_logging(_make_args(log=True), logger_args)

    handlers = captured["config"]["loggers"][logging_utils.LOGGER_KEY]["handlers"]
    assert handlers.count("file") == 1


def test_setup_logging_does_not_enable_file_handler_by_default(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args()

    logging_utils.setup_logging(args, _make_logger_args())

    handlers = captured["config"]["loggers"][logging_utils.LOGGER_KEY]["handlers"]
    assert "file" not in handlers


@pytest.mark.parametrize(
    "arg_name, arg_value, handler_key",
    [
        ("log_level", "WARNING", "level"),
        ("log_file", "logs/docai.log", "filename"),
        ("log_max_size", 4096, "maxBytes"),
        ("log_backup_count", 9, "backupCount"),
    ],
)
def test_setup_logging_updates_file_handler_individual_settings(
    monkeypatch, arg_name, arg_value, handler_key
):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(log=True, **{arg_name: arg_value})

    logging_utils.setup_logging(args, _make_logger_args())

    file_handler = captured["config"]["handlers"]["file"]
    expected = (
        os.path.abspath(arg_value) if arg_name == "log_file" else arg_value
    )
    assert file_handler[handler_key] == expected


def test_setup_logging_updates_file_handler_settings(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(
        log=True,
        log_level="ERROR",
        log_file="logs/docai.log",
        log_max_size=2048,
        log_backup_count=7,
    )

    logging_utils.setup_logging(args, _make_logger_args())

    file_handler = captured["config"]["handlers"]["file"]
    assert file_handler["level"] == "ERROR"
    assert file_handler["filename"].endswith("logs/docai.log")
    assert file_handler["filename"].startswith("/")
    assert file_handler["maxBytes"] == 2048
    assert file_handler["backupCount"] == 7


def test_setup_logging_preserves_absolute_log_path(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(log=True, log_file="/tmp/docai.log")

    logging_utils.setup_logging(args, _make_logger_args())

    file_handler = captured["config"]["handlers"]["file"]
    assert file_handler["filename"] == "/tmp/docai.log"


def test_setup_logging_ignores_zero_rotation_values(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    args = _make_args(log=True, log_max_size=0, log_backup_count=0)

    logging_utils.setup_logging(args, _make_logger_args(ROTATING_CONFIG))

    file_handler = captured["config"]["handlers"]["file"]
    assert file_handler["maxBytes"] == 100
    assert file_handler["backupCount"] == 2


def test_setup_logging_does_not_mutate_input_config(monkeypatch):
    captured = _capture_dictconfig(monkeypatch)
    logger_args = _make_logger_args()

    logging_utils.setup_logging(_make_args(log=True), logger_args)

    assert logger_args["loggers"][logging_utils.LOGGER_KEY]["handlers"] == ["console"]
    assert "config" in captured


@pytest.mark.parametrize("exc", [ValueError("bad"), TypeError("bad"), KeyError("bad")])
def test_setup_logging_invalid_dictconfig(monkeypatch, exc):
    def _raise_invalid(*args, **kwargs):
        raise exc

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _raise_invalid)
    with pytest.raises(SystemExit):
        logging_utils.setup_logging(_make_args(), _make_logger_args())


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
        logging_utils.setup_logging(_make_args(log=True), _make_logger_args())

    assert "can't write to log file location" in captured["msg"]
    assert captured["args"] == ("/tmp/docai.log",)


def test_setup_logging_other_oserror_is_raised(monkeypatch):
    def _raise_other_oserror(*args, **kwargs):
        raise OSError(13, "Permission denied", "/tmp/docai.log")

    monkeypatch.setattr(logging_utils.logging.config, "dictConfig", _raise_other_oserror)
    with pytest.raises(OSError):
        logging_utils.setup_logging(_make_args(log=True), _make_logger_args())


def test_setup_logging_invalid_config_shape_exits():
    with pytest.raises(SystemExit):
        logging_utils.setup_logging(_make_args(), [])
