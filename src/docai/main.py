import asyncio
import logging
import sys

from docai.config.datatypes import Config
from docai.config.loader import load_config
from docai.utils.logging_utils import setup_logging
from docai.workflows import WORKFLOWS

logger = logging.getLogger(__name__)


def main():

    # load arguments
    try:
        config: Config = load_config()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # set up logging
    setup_logging(config.logging_config)
    logger.debug("Logger setup finished")

    logger.info("Hello from DocAI!")

    # start the workflow
    asyncio.run(WORKFLOWS[config.project_config.action](config))


if __name__ == "__main__":
    main()
