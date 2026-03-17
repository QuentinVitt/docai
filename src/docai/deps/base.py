import asyncio
import logging
from typing import Optional

from docai.deps.universal_extractor import (
    extract_dependencies as universal_extract_dependencies,
)
from docai.documentation.datatypes import FileDocType
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content

logger = logging.getLogger(__name__)


async def set_files_dependencies(
    project_path: str, project_files: dict[str, dict], llm: Optional[LLMService] = None
):
    project_files_set = set(project_files.keys())

    async def _safe(f: str) -> tuple[str, set[str]] | None:
        try:
            return await get_dependencies_of_file(
                project_path, f, project_files[f], project_files_set, llm
            )
        except Exception as e:
            logger.warning("Failed to extract dependencies for '%s': %s", f, e)
            return None

    results = await asyncio.gather(*[_safe(f) for f in project_files_set])

    for result in results:
        if result is None:
            continue
        file, deps = result
        project_files[file]["dependencies"] = deps


def create_dependencies_topologically_sorted(
    files: dict[str, dict],
) -> list[set[str]]:

    dependents: dict[str, set[str]] = {}  # file -> set of files that depend on it
    dependency_count: dict[
        str, int
    ] = {}  # file -> number of project files it depends on
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
        for dep in file_info["dependencies"]:
            dependents.setdefault(dep, set()).add(file)

    while zero_dependencies:
        independent_files = set(zero_dependencies)
        zero_dependencies.clear()
        for independent_file in independent_files:
            for dependent_file in dependents.get(independent_file, set()):
                dependency_count[dependent_file] -= 1
                if dependency_count[dependent_file] == 0:
                    zero_dependencies.add(dependent_file)
                    del dependency_count[dependent_file]

        dependency_list.append(independent_files)

    unresolved_dependencies = set(dependency_count.keys())
    if unresolved_dependencies:
        dependency_list.append(unresolved_dependencies)
    if unknown_dependencies:
        dependency_list.append(unknown_dependencies)

    return dependency_list


async def get_dependencies_of_file(
    project_path: str,
    file: str,
    file_info: dict,
    all_files: set[str],
    llm: Optional[LLMService] = None,
) -> tuple[str, set[str]]:

    match file_info.get("file_type"):
        case _:
            if not llm:
                raise ValueError("LLMService not provided")
            result = await universal_extract_dependencies(
                file,
                get_file_content(project_path, file),
                file_info.get("file_type"),
                all_files,
                llm,
            )

    return file, result
