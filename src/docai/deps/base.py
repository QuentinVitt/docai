import asyncio
import logging
import os.path
from typing import Optional

from rich.progress import Progress, TaskID

from docai.deps.universal_extractor import (
    extract_dependencies as universal_extract_dependencies,
)
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import FileDocType
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_content

logger = logging.getLogger(__name__)


async def set_files_dependencies(
    project_path: str,
    project_files: dict[str, dict],
    llm: Optional[LLMService] = None,
    progress: Optional[Progress] = None,
    progress_task: Optional[TaskID] = None,
    cache: Optional[DocumentationCache] = None,
):
    project_files_set = set(project_files.keys())

    async def _safe(f: str) -> tuple[str, set[str]] | None:
        if cache is not None:
            cached_deps = cache.get_file_dependencies(f)
            if cached_deps is not None:
                logger.debug("File dependencies for '%s' found in cache", f)
                if progress is not None and progress_task is not None:
                    progress.advance(progress_task)
                return f, cached_deps
        try:
            result = await get_dependencies_of_file(
                project_path, f, project_files[f], project_files_set, llm
            )
        except Exception as e:
            logger.warning("Failed to extract dependencies for '%s': %s", f, e)
            return None
        if cache is not None:
            _, deps = result
            cache.set_file_dependencies(f, deps)
        if progress is not None and progress_task is not None:
            progress.advance(progress_task)
        return result

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
    match file_info.get("file_doc_type"):
        case FileDocType.OTHER | FileDocType.SKIPPED:
            return file, set()
        case FileDocType.CONFIG | FileDocType.DOCS:
            return file, fuzzy_search_dependencies(project_path, file, all_files)

    # most used programming languages:
    # Python, JavaScript, TypeScript, Java, C#, C++, C, Go, Rust, Kotlin,
    # Swift, PHP, Ruby, Dart, Scala, R, MATLAB, Shell/Bash, Lua, Haskell
    match file_info.get("file_type"):
        case "python":
            from docai.deps.python_extractor import (
                extract_dependencies as python_extract_dependencies,
            )
            result = await python_extract_dependencies(
                file,
                get_file_content(project_path, file),
                all_files,
                llm,
            )
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


_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-/\\")


def fuzzy_search_dependencies(
    project_path: str, file: str, all_files: set[str]
) -> set[str]:
    file_content = get_file_content(project_path, file).lower()
    file_dir = os.path.dirname(file)
    project_files_lower = {pf.lower() for pf in all_files}
    dependencies = set()

    for project_file in all_files:
        if project_file == file:
            continue

        project_file_name = os.path.basename(project_file).lower()
        project_file_lower = project_file.lower()

        start = 0
        while True:
            idx = file_content.find(project_file_name, start)
            if idx == -1:
                break
            start = idx + 1
            end_idx = idx + len(project_file_name)

            # 1.1 End boundary: no path char may follow
            if end_idx < len(file_content) and file_content[end_idx] in _PATH_CHARS:
                continue

            # 1.2 Start boundary: preceding char must be '/' or not a path char
            if (
                idx > 0
                and file_content[idx - 1] in _PATH_CHARS
                and file_content[idx - 1] != "/"
            ):
                continue

            # 2. Extract the path prefix
            # 2.1 Quoted: closing '"' right after filename → scan back through path chars + spaces
            prefix: str | None = None
            if end_idx < len(file_content) and file_content[end_idx] == '"':
                back = idx - 1
                while back >= 0 and (
                    file_content[back] in _PATH_CHARS or file_content[back] == " "
                ):
                    back -= 1
                if back >= 0 and file_content[back] == '"':
                    prefix = file_content[back + 1 : idx]
                # else: closing quote present but no opening one → fall through to 2.2

            # 2.2 Unquoted: scan back through path chars, allow escaped spaces
            if prefix is None:
                back = idx - 1
                while back >= 0:
                    ch = file_content[back]
                    if ch in _PATH_CHARS:
                        back -= 1
                    elif ch == " " and back > 0 and file_content[back - 1] == "\\":
                        back -= 2
                    else:
                        break
                prefix = file_content[back + 1 : idx]

            # Normalise: escaped spaces → spaces, backslashes → forward slashes
            raw = (prefix + project_file_name).replace("\\ ", " ").replace("\\", "/")

            # 3. Matching
            matched = False

            if raw.startswith("/"):
                # 3.1 Absolute path
                matched = raw == (project_path + "/" + project_file_name).lower()

            elif prefix:
                # 3.2 Root-relative exact match
                if raw == project_file_lower:
                    matched = True

                # 3.3 Relative from the current file's directory
                if not matched:
                    resolved = os.path.normpath(os.path.join(file_dir, raw)).replace(
                        "\\", "/"
                    )
                    matched = resolved in project_files_lower

            else:
                # 3.4 Filename only: match if project_file is in the same directory
                pf_dir = os.path.dirname(project_file)
                matched = pf_dir == file_dir

            if matched:
                dependencies.add(project_file)
                break

    return dependencies
