import copy
import logging
import logging.config
from os.path import abspath

LOGGER_KEY = "docai_project"


def setup_logging(cli_args, logger_args):
    logger_config = copy.deepcopy(logger_args)

    try:
        if cli_args.verbose:
            logger_config['loggers'][LOGGER_KEY]['level'] = logging.DEBUG
        elif cli_args.quiet:
            logger_config['loggers'][LOGGER_KEY]['level'] = logging.WARNING
        elif cli_args.silent:
            logger_config['loggers'][LOGGER_KEY]['level'] = logging.CRITICAL

        if cli_args.log:
            handlers = logger_config['loggers'][LOGGER_KEY]['handlers']
            if "file" not in handlers:
                handlers.append('file')
        if cli_args.log_level:
            logger_config['handlers']['file']['level'] = cli_args.log_level
        if cli_args.log_file:
            logger_config['handlers']['file']['filename'] = abspath(cli_args.log_file)
        if cli_args.log_max_size:
            logger_config['handlers']['file']['maxBytes'] = cli_args.log_max_size
        if cli_args.log_backup_count:
            logger_config['handlers']['file']['backupCount'] = cli_args.log_backup_count
    except (KeyError, TypeError, AttributeError) as exc:
        logging.critical("Invalid logging configuration: %s", exc, exc_info=True)
        exit(1)

    try:
        logging.config.dictConfig(logger_config)
    except OSError as exc:
        if exc.errno == 30:
            log_path = (
                logger_config.get("handlers", {}).get("file", {}).get("filename")
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
