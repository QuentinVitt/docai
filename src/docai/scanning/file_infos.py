import logging
import os

import filetype

logger = logging.getLogger(__name__)


def get_file_type(project_path: str, path: str) -> str | None:
    file = os.path.join(project_path, path)

    if not os.path.isfile(file):
        logger.error("File '%s' does not exist", file, exc_info=True)
        raise FileNotFoundError(f"File '{file}' does not exist")

    _, file_extension = os.path.splitext(file)
    if file_extension != "":
        return file_extension[1:]

    kind = filetype.guess(file)
    if kind is not None:
        return kind.extension

    logger.warning("File type of '%s' could not be determined", file)
    return None


def get_file_content(project_path: str, path: str) -> str:
    file = os.path.join(project_path, path)
    if not os.path.isfile(file):
        logger.error("File '%s' does not exist", file)
        raise FileNotFoundError(f"File '{file}' does not exist")
    with open(file, "r") as f:
        return f.read()
