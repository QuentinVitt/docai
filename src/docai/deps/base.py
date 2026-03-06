import asyncio
import logging
from typing import Optional

from docai.deps.universal_extractor import (
    extract_dependencies as universal_extract_dependencies,
)
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content, get_file_type

logger = logging.getLogger("docai_project")


async def create_dependencies_list(
    files: set[str], llm: Optional[LLMService]
) -> list[set[str]]:

    dependencies: dict[str, set[str]] = {}  # file -> set of files that depend on it
    dependency_count: dict[str, int] = {}  # file -> number files it depends on
    zero_dependencies: set[str] = set()  # files that depend on no other files
    unknown_dependencies: set[str] = set()  # files with unknown dependencies
    dependency_list: list[set[str]] = []  # list of files in order of dependencies

    files_list = list(files)
    results = await asyncio.gather(
        *[get_dependencies_of_file(f, files, llm) for f in files_list],
        return_exceptions=True,
    )

    for file, result in zip(files_list, results):
        if isinstance(result, Exception):
            unknown_dependencies.add(file)
            continue

        if not result:
            zero_dependencies.add(file)
            continue

        for file_dependency in result:
            dependencies.setdefault(file_dependency, set()).add(file)
            dependency_count[file] = dependency_count.get(file, 0) + 1

    while zero_dependencies:
        independent_files = set(zero_dependencies)
        zero_dependencies.clear()
        for independent_file in independent_files:
            for dependent_files in dependencies.get(independent_file, set()):
                dependency_count[dependent_files] -= 1
                if dependency_count[dependent_files] == 0:
                    zero_dependencies.add(dependent_files)

        dependency_list.append(independent_files)

    unresolved_dependencies = {
        file for file in dependency_count if dependency_count[file] > 0
    }
    if unresolved_dependencies:
        dependency_list.append(unresolved_dependencies)
    if unknown_dependencies:
        dependency_list.append(unknown_dependencies)

    return dependency_list


async def get_dependencies_of_file(
    file: str, all_files: set[str], llm: Optional[LLMService] = None
) -> list[str]:

    file_type = get_file_type(file)

    match file_type:
        case _:
            if not llm:
                raise ValueError("LLMService not provided")
            return await universal_extract_dependencies(
                file,
                get_file_content(file),
                file_type,
                all_files,
                llm,
            )
