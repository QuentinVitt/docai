import logging
import os
from threading import Lock

import filetype

logger = logging.getLogger("docai_project")


def get_file_type(file: str) -> str | None:
    # check if this is a real file
    if not os.path.isfile(file):
        logger.error("File '%s' does not exist", file, exc_info=True)
        raise FileNotFoundError(f"File '{file}' does not exist")

    # check for extention
    _, file_extension = os.path.splitext(file)
    if file_extension != "":
        logger.debug("File type of '%s' identified via extension", file)
        return file_extension[1:]

    # check for magic numbers
    kind = filetype.guess(file)
    if kind is not None:
        logger.debug("File type of '%s' identified via magic numbers", file)
        return kind.extension

    # if file type could not be determined return None
    logger.debug("File type of '%s' could not be determined", file)
    return None
