def get_file_type(file: str) -> str:
    # TODO: caching
    # TODO: logging
    # TODO: test logic
    if "." not in file:
        # TODO: implement fallback logic - what happends if the file type could not be detected via extension? Maybe it is an executable or not even a file
        raise ValueError("Could not detect file type")
    return file.split(".")[-1]
