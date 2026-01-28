import logging
import sys

from docai.config.loader import ConfigError, load_config
from docai.utils.logging_utils import setup_logging
from docai.workflows import WORKFLOWS

logger = logging.getLogger("docai_project")

def document(config):
    logger.info("Start documenting %s", config.project_args.working_dir)
    # First we do dependencies
    # Then we do documentation for dependent-free dependencies - AI agent can access already documented files
    pass

def main():

    # load arguments
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not (config.cli_args.quiet or config.cli_args.silent):
        print("Hello from DocAI!")

    # set up logging
    setup_logging(config.cli_args, config.logger_args)
    logger.debug("Logger setup finished")

    # start the workflow
    WORKFLOWS[config.project_args.action](config)

if __name__ == "__main__":
    main()
