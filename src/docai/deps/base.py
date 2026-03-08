import asyncio
import logging
from typing import Optional

from docai.deps.universal_extractor import (
    extract_dependencies as universal_extract_dependencies,
)
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content

logger = logging.getLogger("docai_project")


async def set_files_dependencies(
    project_files: dict[str, dict], llm: Optional[LLMService] = None
):
    project_files_set = set(project_files.keys())
    dependencies_list = await asyncio.gather(
        *[
            get_dependencies_of_file(f, project_files[f], project_files_set, llm)
            for f in project_files_set
        ],
        return_exceptions=True,
    )

    for result in dependencies_list:
        if isinstance(result, Exception):
            continue
        file, deps = result  # type: ignore
        project_files[file]["dependencies"] = deps


async def create_dependencies_topologically_sorted(
    files: dict[str, dict],
) -> list[set[str]]:

    dependency_count: dict[str, int] = {}  # file -> number files it depends on
    zero_dependencies: set[str] = set()  # files that depend on no other files
    unknown_dependencies: set[str] = set()  # files with unknown dependencies
    dependency_list: list[set[str]] = []  # list of files in order of dependencies

    for file, file_info in files.items():
        if "dependencies" not in file_info:
            unknown_dependencies.add(file)
            continue

        if not file_info["dependencies"]:
            zero_dependencies.add(file)
            continue

        dependency_count[file] = len(file_info["dependencies"])

    while zero_dependencies:
        independent_files = set(zero_dependencies)
        zero_dependencies.clear()
        for independent_file in independent_files:
            for dependent_files in files[independent_file]["dependencies"]:
                dependency_count[dependent_files] -= 1
                if dependency_count[dependent_files] == 0:
                    zero_dependencies.add(dependent_files)
                    del dependency_count[dependent_files]

        dependency_list.append(independent_files)

    unresolved_dependencies = set(dependency_count.keys())
    if unresolved_dependencies:
        dependency_list.append(unresolved_dependencies)
    if unknown_dependencies:
        dependency_list.append(unknown_dependencies)

    return dependency_list


async def get_dependencies_of_file(
    file: str, file_info: dict, all_files: set[str], llm: Optional[LLMService] = None
) -> tuple[str, set[str]]:

    match file_info.get("file_type"):
        case _:
            if not llm:
                raise ValueError("LLMService not provided")
            result = await universal_extract_dependencies(
                file,
                get_file_content(file),
                file_info.get("file_type"),
                all_files,
                llm,
            )

    return file, result
