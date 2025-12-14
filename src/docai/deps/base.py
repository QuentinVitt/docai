import logging

from docai.scanning.file_infos import get_file_type

logger = logging.getLogger("docai_project")

# def get_dependencies_list(files: set[str]) -> list[str]:
#     raise NotImplementedError("Function not tested")
#     # TODO: cache
#     # TODO: logging
#     # TODO: test logic

#     dependencies: dict[str, set[str]] = {}  # file -> set of files that depend on it
#     dependency_count: dict[str, int] = {}  # file -> number files it depends on
#     zero_dependencies: set[str] = set()  # files that depend on no other files
#     dependency_list: list[str] = []  # list of files in order of dependencies

#     for file in files:
#         file_dependencies = get_dependencies_of_file(file)
#         if not file_dependencies:
#             zero_dependencies.add(file)
#             continue

#         for file_dependency in file_dependencies:
#             if file_dependency not in dependencies:
#                 dependencies[file_dependency] = set()
#             dependencies[file_dependency].add(file)

#             dependency_count[file] = dependency_count.get(file, 0) + 1

#     while zero_dependencies:
#         independent_file: str = zero_dependencies.pop()
#         for dependent_files in dependencies.get(independent_file, set()):
#             dependency_count[dependent_files] -= 1
#             if dependency_count[dependent_files] == 0:
#                 zero_dependencies.add(dependent_files)
#         dependency_list.append(independent_file)

#     return dependency_list


def get_dependencies_of_file(file: str, file_type: str | None = None) -> list[str]:
    # TODO: caching
    # TODO: logging
    # TODO: test logic
    raise NotImplementedError("Function not implemented")

    # implemented in the section scanning

    if not file_type:
        file_type = get_file_type(file)

    match file_type:
        case _:
            raise NotImplementedError("Function not implemented")
