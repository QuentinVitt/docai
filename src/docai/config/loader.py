import argparse
import os
from asyncio import Lock, Semaphore
from dataclasses import dataclass
from importlib import resources

import yaml

LOG_CONFIG_PACKAGE = "docai.config"
LOG_CONFIG_FILE = "logging_defaults.yaml"

LLM_CONFIG_PACKAGE = "docai.config"
LLM_CONFIG_FILE = "llm_config.yaml"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectArgs:
    action: str
    working_dir: str
    interactive: bool


@dataclass(frozen=True)
class Config:
    project_args: ProjectArgs
    logger_args: dict
    cli_args: argparse.Namespace
    llm_args: dict


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="docai",
        description="DocAI is a command-line tool for automating documentation of software projects.",  # TODO: improve the description text
        epilog="Enjoy the power of DocAI!",  # TODO: improve the epilog text
    )
    parser.add_argument(
        "action",
        nargs="?",
        type=str,
        choices=["document"],
        default="document",
        help="action to perform",
    )

    parser.add_argument(
        "-d", "--directory", type=str, help="path to directory to work on"
    )

    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "-v", "--verbose", action="store_true", help="increase output verbosity"
    )
    verbosity_group.add_argument(
        "-q", "--quiet", action="store_true", help="decrease output verbosity"
    )
    verbosity_group.add_argument(
        "-s", "--silent", action="store_true", help="disable all output"
    )

    parser.add_argument("-l", "--log", action="store_true", help="enable file logging")

    log_file_group = parser.add_argument_group()
    log_file_group.add_argument(
        "-ll",
        "--log_level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="set log level",
    )
    log_file_group.add_argument("-lf", "--log_file", type=str, help="set log file path")
    log_file_group.add_argument(
        "-lms", "--log_max_size", type=int, help="set log file max size in bytes"
    )
    log_file_group.add_argument(
        "-lbc", "--log_backup_count", type=int, help="set log file backup count"
    )

    parser.add_argument(
        "-i", "--interactive", action="store_true", help="run in interactive mode"
    )

    llm_group = parser.add_argument_group()
    llm_group.add_argument("--llm_default", type=str, help="select default LLM profile")
    llm_group.add_argument(
        "--llm_fallback", type=str, help="select fallback LLM profile"
    )

    args = parser.parse_args()

    log_file_args = ("log_level", "log_file", "log_max_size", "log_backup_count")
    if any(getattr(args, name) for name in log_file_args) and not args.log:
        parser.error("--log is required when using log file options")

    return args


def build_project_args(args) -> ProjectArgs:
    try:
        working_dir = os.path.abspath(args.directory) if args.directory else os.getcwd()
    except OSError as exc:
        raise ConfigError(f"Error identifying working directory: {exc}") from exc

    return ProjectArgs(
        action=args.action,
        working_dir=working_dir,
        interactive=args.interactive,
    )


def load_config_file(config_package: str, config_file: str) -> dict:
    try:
        with resources.open_text(config_package, config_file) as config_test:
            config = yaml.safe_load(config_test)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file '{config_file}' not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid configuration file '{config_file}': {exc}") from exc

    if not isinstance(config, dict):
        raise ConfigError(
            f"Configuration file '{config_file}' must contain a YAML mapping"
        )

    return config


def setup_llm(llm_args: dict):
    max_concurrency = llm_args.get("globals", {}).get("max_concurrency", 1)
    semaphore = Semaphore(max_concurrency)
    inflight_requests = max_concurrency * 2
    llm_args["semaphore"] = semaphore
    llm_args["inflight_semaphore"] = Semaphore(inflight_requests)


def load_config() -> Config:
    cli_args = parse_arguments()
    project_args = build_project_args(cli_args)
    logger_args = load_config_file(LOG_CONFIG_PACKAGE, LOG_CONFIG_FILE)
    llm_args = load_config_file(LLM_CONFIG_PACKAGE, LLM_CONFIG_FILE)
    setup_llm(llm_args)

    return Config(
        project_args=project_args,
        logger_args=logger_args,
        cli_args=cli_args,
        llm_args=llm_args,
    )
