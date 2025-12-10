from docai.scanning.file_infos import get_file_type


def test_get_file_type_pytest():
    file = "example.txt"
    assert get_file_type(file) == "txt"
