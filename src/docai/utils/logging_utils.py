import copy
import logging
import logging.config

LOGGER_KEY = "docai"


def setup_logging(logging_config: dict):
    logging_config = copy.deepcopy(logging_config)

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
