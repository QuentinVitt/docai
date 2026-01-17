import logging
import logging.config
from importlib import resources
from os.path import abspath

import yaml

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "logging_defaults.yaml"

LOGGER_KEY = "docai_project"


def setup_logging(args):
    try:
        config_test = resources.open_text(CONFIG_PACKAGE, CONFIG_FILE)
    except FileNotFoundError:
        logging.critical("Logging configuration file not found", exc_info=True)
        exit(1)

    try:
        config = yaml.safe_load(config_test)
    except yaml.YAMLError as exc:
        logging.critical("Invalid logging configuration file: %s", exc, exc_info=True)
        exit(1)

    root = logging.getLogger()

    if args.verbose:
        config['loggers'][LOGGER_KEY]['level'] = logging.DEBUG
    elif args.quiet:
        config['loggers'][LOGGER_KEY]['level'] = logging.WARNING
    elif args.silent:
        config['loggers'][LOGGER_KEY]['level'] = logging.CRITICAL

    if args.log:
        config['loggers'][LOGGER_KEY]['handlers'].append('file')
    if args.log_level:
        config['handlers']['file']['level'] = args.log_level
    if args.log_file:
        config['handlers']['file']['filename'] = abspath(args.log_file)
    if args.log_max_size:
        config['handlers']['file']['maxBytes'] = args.log_max_size
    if args.log_backup_count:
        config['handlers']['file']['backupCount'] = args.log_backup_count

    try:
        logging.config.dictConfig(config)
    except OSError as exc:
        if exc.errno == 30:
            log_path = config['handlers']['file']['filename']
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
