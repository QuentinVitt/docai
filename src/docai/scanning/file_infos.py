import logging
import os
from threading import Lock

import filetype

logger = logging.getLogger("docai_project")


def get_file_type(file: str) -> str:
    # check if this is a real file
    if not os.path.isfile(file):
        logger.error(f"File '{file}' does not exist")
        raise FileNotFoundError(f"File '{file}' does not exist")

    # check for extention
    _, file_extension = os.path.splitext(file)
    if file_extension != "":
        logger.debug(f"File type of '{file}' identified via extension")
        return file_extension[1:]

    # check for magic numbers
    kind = filetype.guess(file)
    if kind is not None:
        logger.debug(f"File type of '{file}' identified via magic numbers")
        return kind.extension

    # if file type could not be determined return None
    logger.debug(f"File type of '{file}' could not be determined")
    return None
