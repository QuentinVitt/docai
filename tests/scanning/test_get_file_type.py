import os

import pytest

from docai.scanning.file_infos import get_file_type

# def test_get_file_type_1():
#     cwd = os.getcwd()
#     file_path = os.path.join(cwd, "tmp_tests/example.txt")
#     os.makedirs(os.path.dirname(file_path), exist_ok=True)
#     with open(file_path, "w") as f:
#         f.write("Hello, world!")

#     assert get_file_type(file_path) == "txt"


def test_get_file_type_2():
    """
    Test get_file_type function with a non-existing file
    """
    cwd = os.getcwd()
    file_path = os.path.join(cwd, "tmp_tests/non_existing.txt")

    with pytest.raises(FileNotFoundError, match=f"File '{file_path}' does not exist"):
        get_file_type(file_path)


def test_get_file_type_3():
    """
    Test get_file_type function with a directory and not a file
    """
    cwd = os.getcwd()
    dir_path = os.path.join(cwd, "tmp_tests/dir_not_file")
    os.makedirs(dir_path, exist_ok=True)

    with pytest.raises(FileNotFoundError, match=f"File '{dir_path}' does not exist"):
        get_file_type(dir_path)
