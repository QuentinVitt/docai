import logging
import logging.config
from importlib import resources

import yaml

CONFIG_PACKAGE = "docai.config"
CONFIG_FILE = "logging_defaults.yaml"

LOGGER_KEY = "docai_project"


def setup_logging(args):
    # TODO: customise with args
    try:
        config_test = resources.open_text(CONFIG_PACKAGE, CONFIG_FILE)
    except FileNotFoundError:
        logging.critical("Logging configuration file not found", exc_info=True)
        exit(1)

    config = yaml.safe_load(config_test)

    root = logging.getLogger()

    logging.config.dictConfig(config)
