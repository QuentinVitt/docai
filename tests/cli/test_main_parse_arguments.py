import sys

import pytest

from docai.config.loader import parse_arguments


def _parse(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["docai", *args])
    return parse_arguments()


def test_parse_arguments_defaults(monkeypatch):
    args = _parse(monkeypatch)
    assert args.directory is None
    assert args.verbose is False
    assert args.quiet is False
    assert args.silent is False
    assert args.log is False
    assert args.log_level is None
    assert args.log_file is None
    assert args.log_max_size is None
    assert args.log_backup_count is None
    assert args.interactive is False


def test_parse_arguments_directory(monkeypatch):
    args = _parse(monkeypatch, "--directory", "/tmp/project")
    assert args.directory == "/tmp/project"


@pytest.mark.parametrize(
    "flag, attr",
    [
        ("-v", "verbose"),
        ("-q", "quiet"),
        ("-s", "silent"),
    ],
)
def test_parse_arguments_verbosity_flags(monkeypatch, flag, attr):
    args = _parse(monkeypatch, flag)
    assert getattr(args, attr) is True
    assert args.verbose is (attr == "verbose")
    assert args.quiet is (attr == "quiet")
    assert args.silent is (attr == "silent")


@pytest.mark.parametrize(
    "flags",
    [
        ("-v", "-q"),
        ("-v", "-s"),
        ("-q", "-s"),
    ],
)
def test_parse_arguments_verbosity_conflicts(monkeypatch, flags):
    with pytest.raises(SystemExit):
        _parse(monkeypatch, *flags)


def test_parse_arguments_log_flag(monkeypatch):
    args = _parse(monkeypatch, "--log")
    assert args.log is True


def test_parse_arguments_interactive_flag(monkeypatch):
    args = _parse(monkeypatch, "--interactive")
    assert args.interactive is True


@pytest.mark.parametrize(
    "args",
    [
        ("--log_level", "DEBUG"),
        ("--log_file", "docai.log"),
        ("--log_max_size", "1024"),
        ("--log_backup_count", "3"),
        ("--log_level", "INFO", "--log_file", "docai.log"),
    ],
)
def test_parse_arguments_log_file_options_require_log(monkeypatch, args):
    with pytest.raises(SystemExit):
        _parse(monkeypatch, *args)


def test_parse_arguments_log_file_options_with_log(monkeypatch):
    args = _parse(
        monkeypatch,
        "--log",
        "--log_level",
        "ERROR",
        "--log_file",
        "docai.log",
        "--log_max_size",
        "2048",
        "--log_backup_count",
        "7",
    )
    assert args.log is True
    assert args.log_level == "ERROR"
    assert args.log_file == "docai.log"
    assert args.log_max_size == 2048
    assert args.log_backup_count == 7


def test_parse_arguments_invalid_log_level(monkeypatch):
    with pytest.raises(SystemExit):
        _parse(monkeypatch, "--log", "--log_level", "TRACE")
