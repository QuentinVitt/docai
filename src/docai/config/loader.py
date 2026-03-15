import argparse
import asyncio
import os
from importlib import resources

import yaml

import docai.config.datatypes as dt
from docai.llm.agent_tools import make_tool_registry

LOG_CONFIG_PACKAGE = "docai.config"
LOG_CONFIG_FILE = "logging_config.yaml"

LLM_CONFIG_PACKAGE = "docai.config"
LLM_CONFIG_FILE = "llm_config.yaml"


class ConfigError(RuntimeError):
    pass


def parse_arguments() -> argparse.Namespace:
    # -------------------------------------------------------------------------
    # Shared arguments — inherited by every subcommand via parents=
    # -------------------------------------------------------------------------
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Path to the project directory (default: current directory)",
    )
    verbosity = shared.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress output except errors"
    )
    verbosity.add_argument(
        "-s", "--silent", action="store_true", help="Suppress all output"
    )
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="Increase verbosity"
    )

    # -------------------------------------------------------------------------
    # Main parser
    # -------------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        prog="docai",
        description=(
            "Generate AI-powered documentation for any software project. "
            "Analyzes your codebase and produces structured docs for every "
            "file, class, and function."
        ),
        epilog=(
            "Run 'docai <command> --help' for more information on a specific command."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        dest="action",
        title="commands",
        metavar="<command>",
    )
    subparsers.required = True

    # -------------------------------------------------------------------------
    # document
    # -------------------------------------------------------------------------
    document_parser = subparsers.add_parser(
        "document",
        parents=[shared],
        help="Generate documentation for a project",
        description="Analyze a codebase and generate structured documentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  docai document ./my-project\n  docai document . --no-cache",
    )

    document_parser.add_argument(
        "-lp",
        "--llm-profile",
        type=str,
        default="default",
        metavar="PROFILE",
        help="Select specific LLM profile to use for document generation",
    )
    llm_cache_group = document_parser.add_mutually_exclusive_group()
    llm_cache_group.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Disable caching of LLM responses",
    )
    llm_cache_group.add_argument(
        "--new-cache",
        action="store_true",
        default=False,
        help="Clear existing cache and generate new documentation",
    )

    return parser.parse_args()


def build_project_config(args: argparse.Namespace) -> dt.ProjectConfig:
    try:
        working_dir = (
            args.directory
            if os.path.isabs(args.directory)
            else os.path.abspath(os.path.join(os.getcwd(), args.directory))
        )
    except OSError as exc:
        raise ConfigError(f"Error identifying working directory: {exc}") from exc

    if not os.path.isdir(working_dir):
        raise ConfigError(f"Not a directory: {working_dir}")
    if not os.access(working_dir, os.R_OK | os.W_OK):
        raise ConfigError(f"Cannot read/write working directory: {working_dir}")

    try:
        action = dt.ProjectAction(args.action)
    except ValueError as exc:
        raise ConfigError(f"Unknown action: {args.action}") from exc

    return dt.ProjectConfig(action=action, working_dir=working_dir)


def build_logger_config(args: argparse.Namespace) -> dict:

    try:
        with resources.open_text(LOG_CONFIG_PACKAGE, LOG_CONFIG_FILE) as config_test:
            config = yaml.safe_load(config_test)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file '{LOG_CONFIG_FILE}' not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid configuration file '{LOG_CONFIG_FILE}': {exc}"
        ) from exc

    if not isinstance(config, dict):
        raise ConfigError(
            f"Configuration file '{LOG_CONFIG_FILE}' must contain a YAML mapping"
        )

    try:
        if args.verbose:
            config["loggers"]["docai"]["level"] = "DEBUG"
        elif args.quiet:
            config["loggers"]["docai"]["level"] = "ERROR"
        elif args.silent:
            config["loggers"]["docai"]["level"] = "CRITICAL"
    except KeyError as exc:
        raise ConfigError(
            f"Configuration file '{LOG_CONFIG_FILE}' must contain a 'loggers' section with a 'docai' logger"
        ) from exc

    return config


def build_llm_config(args: argparse.Namespace, project_dir: str):

    try:
        with resources.open_text(LLM_CONFIG_PACKAGE, LLM_CONFIG_FILE) as config_test:
            config = yaml.safe_load(config_test)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file '{LLM_CONFIG_FILE}' not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid configuration file '{LLM_CONFIG_FILE}': {exc}"
        ) from exc

    if not isinstance(config, dict):
        raise ConfigError(
            f"Configuration file '{LLM_CONFIG_FILE}' must contain a YAML mapping"
        )
    for required in ("profiles", "models", "providers", "globals"):
        if required not in config:
            raise ConfigError(
                f"Configuration file '{LLM_CONFIG_FILE}' must contain a '{required}' section"
            )

    if args.llm_profile not in config["profiles"]:
        raise ConfigError(
            f"LLM profile '{args.llm_profile}' not found in configuration"
        )

    profile = config["profiles"][args.llm_profile]
    if not isinstance(profile, list):
        raise ConfigError(
            f"LLM profile '{args.llm_profile}' contains invalid configuration: {profile}"
        )
    connections = []
    for c in profile:
        # set model_config
        if not isinstance(c, dict):
            raise ConfigError(
                f"LLM profile '{args.llm_profile}' contains invalid configuration: {c}"
            )
        if "model" not in c:
            raise ConfigError(
                f"LLM profile '{args.llm_profile}' contains invalid configuration: {c}"
            )

        model_name = c["model"]
        if model_name not in config["models"]:
            raise ConfigError(
                f"LLM profile '{args.llm_profile}' contains invalid configuration: {c}"
            )
        model = config["models"][model_name]
        try:
            model_config = dt.LLMModelConfig(**model)
        except Exception as e:
            raise ConfigError(
                f"LLM profile '{args.llm_profile}' contains invalid configuration: {c}"
            ) from e

        # set provider_config
        if "provider" not in c:
            raise ConfigError(
                f"LLM profile '{args.llm_profile}' contains invalid configuration: {c}"
            )
        provider_name = c["provider"]
        if provider_name not in config["providers"]:
            raise ConfigError(
                f"LLM profile '{args.llm_profile}' contains invalid configuration: {c}"
            )
        provider = config["providers"][provider_name]
        if "api_key" in provider:
            api_key = provider["api_key"]
        elif "api_key_env" in provider:
            env_var = provider["api_key_env"]
            api_key = os.environ.get(env_var)
            if api_key is None:
                raise ConfigError(
                    f"Environment variable '{env_var}' for provider '{provider_name}' is not set"
                )
        else:
            raise ConfigError(
                f"Provider '{provider_name}' must have 'api_key' or 'api_key_env'"
            )
        provider_config = dt.LLMProviderConfig(name=provider_name, api_key=api_key)

        profile_config = dt.LLMProfileConfig(
            model=model_config, provider=provider_config
        )
        connections.append(profile_config)

    # set up concurrency config
    concurrency_config = dt.LLMConcurrencyConfig(
        max_concurrency=config["globals"]["max_concurrent_requests"],
        concurrency_semaphore=asyncio.Semaphore(
            config["globals"]["max_concurrent_requests"]
        ),
    )

    # set up retry config
    retry = config.get("retry", {})
    retry_config = dt.LLMRetryConfig(
        max_retries=retry.get("max_retries", 3),
        max_validation_retries=retry.get("max_validation_retries", 2),
        retry_delay=retry.get("retry_delay", 1000)
        / 1000,  # YAML is ms, runner uses seconds
        retry_on=retry.get("retry_on", ["5..", "408", "429"]),
    )

    # set up cache config
    cache = config.get("cache", {})
    cache_dir = os.path.join(project_dir, cache.get("cache_dir", ".docai/cache/llm"))
    cache_config = dt.LLMCacheConfig(
        use_cache=not args.no_cache,
        start_with_clean_cache=args.new_cache,
        cache_dir=cache_dir,
        max_disk_size=cache.get("max_disk_size", 1_000_000_000),
        max_age=cache.get("max_age", 86_400),
        max_lru_size=cache.get("max_lru_size", 1_000),
        model_config_strategy=dt.LLMCacheModelConfigStrategy(
            cache.get("model_config_strategy", "newest")
        ),
    )

    # set up tools
    tool_registry = make_tool_registry(project_dir)

    return dt.LLMConfig(
        profiles=connections,
        concurrency=concurrency_config,
        retry=retry_config,
        cache=cache_config,
        tools=tool_registry,
    )


def load_config():
    cli_args: argparse.Namespace = parse_arguments()
    project_config: dt.ProjectConfig = build_project_config(cli_args)
    logging_config: dict = build_logger_config(cli_args)
    llm_config: dt.LLMConfig = build_llm_config(cli_args, project_config.working_dir)

    return dt.Config(
        project_config=project_config,
        logging_config=logging_config,
        llm_config=llm_config,
    )
