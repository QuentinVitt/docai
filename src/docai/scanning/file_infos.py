import os

import filetype


def get_file_type(file: str) -> str:
    # TODO: caching
    # TODO: logging
    # TODO: test logic

    # check if this is a real file
    if not os.path.isfile(file):
        raise FileNotFoundError(f"File '{file}' does not exist")

    # check for extention

    # check for magic numbers
    #
    #
    kind = filetype.guess(file)
    if kind is None:
        raise ValueError("Could not detect file type")

    return kind.extension
