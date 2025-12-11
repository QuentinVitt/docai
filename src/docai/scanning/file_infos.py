import logging
import os

import filetype


def get_file_type(file: str) -> str:
    # TODO: logging
    logging.warning("Remain calm!")
    # check if this is a real file
    if not os.path.isfile(file):
        raise FileNotFoundError(f"File '{file}' does not exist")

    # check for extention
    _, file_extension = os.path.splitext(file)
    if file_extension != "":
        return file_extension[1:]

    # check for magic numbers
    kind = filetype.guess(file)
    if kind is not None:
        return kind.extension

    # if file type could not be determined return None
    return None
