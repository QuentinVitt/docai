import os


def get_project_files(project_path: str) -> set[str]:
    # create a set of all files in the project
    return {
        os.path.join(root, file)
        for root, _, files in os.walk(project_path)
        for file in files
    }


def get_project_tree(path: str) -> dict[str, list[str]]:
    # create a dictionary of all files in the project, grouped by directory
    return {
        root: [os.path.join(root, file) for file in files]
        for root, _, files in os.walk(path)
    }
