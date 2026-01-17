import sys
from docai.utils.logging_utils import setup_logging
import argparse
import logging
import os

logger = logging.getLogger("docai_project")

def parse_arguments():
    parser = argparse.ArgumentParser(
        prog='docai',
        description='DocAI is a command-line tool for automating documentation of software projects.', # TODO: improve the description text
        epilog='Enjoy the power of DocAI!' # TODO: improve the epilog text
    )
    parser.add_argument(
        "action",
        nargs="?",
        type=str,
        choices=["document"],
        default="document",
        help="action to perform",
    )

    parser.add_argument("-d", "--directory", type=str, help="path to directory to work on")

    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument("-v", "--verbose", action="store_true", help="increase output verbosity")
    verbosity_group.add_argument("-q", "--quiet", action="store_true", help="decrease output verbosity")
    verbosity_group.add_argument('-s', '--silent', action="store_true", help="disable all output")

    parser.add_argument('--log', action='store_true', help="enable file logging")

    log_file_group = parser.add_argument_group()
    log_file_group.add_argument('--log_level', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help="set log level")
    log_file_group.add_argument('--log_file', type=str, help="set log file path")
    log_file_group.add_argument('--log_max_size', type=int, help="set log file max size in bytes")
    log_file_group.add_argument('--log_backup_count', type=int, help="set log file backup count")

    parser.add_argument("-i", "--interactive", action="store_true", help="run in interactive mode")

    args = parser.parse_args()

    log_file_args = ("log_level", "log_file", "log_max_size", "log_backup_count")
    if any(getattr(args, name) for name in log_file_args) and not args.log:
        parser.error("--log is required when using log file options")

    return args

def document(args):

    # First we do dependencies
    # Then we do documentation for dependent-free dependencies - AI agent can access already documented files
    pass

def main():
    args = parse_arguments()
    if not (args.quiet or args.silent):
        print("Hello from DocAI!")

    # set up logging
    setup_logging(args)

    # Identify the directory to work on
    try:
        working_dir = os.path.abspath(args.directory) if args.directory else os.getcwd()
        logger.debug(f"Identified working directory: {working_dir}")
    except Exception as e:
        logger.critical(f"Error identifying working directory: {e}")
        sys.exit(1)

    # identify what needs to be done - for the time beeing only documentation
    match args.action:
        case _:
            document()


if __name__ == "__main__":
    main()
