import copy
import logging
import logging.config

from rich.console import Console
from rich.logging import RichHandler

LOGGER_KEY = "docai"

_console = Console()


def get_console() -> Console:
    return _console


def setup_logging(logging_config: dict):
    logging_config = copy.deepcopy(logging_config)

    # Identify which loggers (and root) declared the "console" handler, then strip
    # it from the config before calling dictConfig — we'll add RichHandler manually
    # so all console output goes through the shared Console instance.
    loggers_with_console: set[str] = set()

    for name, logger_cfg in logging_config.get("loggers", {}).items():
        if "console" in logger_cfg.get("handlers", []):
            loggers_with_console.add(name)
            logger_cfg["handlers"] = [h for h in logger_cfg["handlers"] if h != "console"]

    root_cfg = logging_config.get("root", {})
    root_has_console = "console" in root_cfg.get("handlers", [])
    if root_has_console:
        root_cfg["handlers"] = [h for h in root_cfg["handlers"] if h != "console"]

    logging_config.get("handlers", {}).pop("console", None)

    try:
        logging.config.dictConfig(logging_config)
    except OSError as exc:
        if exc.errno == 30:
            log_path = (
                logging_config.get("handlers", {}).get("file", {}).get("filename")
            )
            logging.critical(
                "Failed to configure logging: can't write to log file location '%s'",
                log_path,
                exc_info=True,
            )
            exit(1)
        raise
    except (ValueError, TypeError, KeyError) as exc:
        logging.critical("Invalid logging configuration: %s", exc, exc_info=True)
        exit(1)

    rich_handler = RichHandler(
        console=_console,
        show_path=False,
        show_time=False,
        markup=True,
    )
    rich_handler.setLevel(logging.DEBUG)

    for name in loggers_with_console:
        logging.getLogger(name).addHandler(rich_handler)

    if root_has_console:
        logging.getLogger().addHandler(rich_handler)
