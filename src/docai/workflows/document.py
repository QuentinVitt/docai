import asyncio
import json
import logging
import os
from collections import defaultdict

from docai.config.datatypes import Config
from docai.deps.base import (
    create_dependencies_topologically_sorted,
    set_files_dependencies,
)
from docai.documentation.base import (
    create_file_documentation,
    identify_entities,
    set_file_doc_type,
)
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import FileDocType
from docai.documentation.package_documentation import document_package
from docai.documentation.project_documentation import document_project
from docai.output.markdown import write_markdown_docs
from docai.llm.agent_tools import make_tool_registry
from docai.llm.errors import LLMError
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_type
from docai.scanning.project_infos import get_project_files

logger = logging.getLogger(__name__)


async def run(config: Config):
    logger.info("Documenting %s", config.project_config.working_dir)
    # 0.1 set up documentation cache
    cache = DocumentationCache(
        config.project_config.documentation_cache, config.project_config.working_dir
    )

    # 0.2 create tool registry and llm service
    tool_registry = make_tool_registry(config.project_config.working_dir, cache)
    try:
        llm: LLMService = await LLMService.create(config.llm_config, tool_registry)
    except LLMError as e:
        logger.error("Could not initialize LLM service: %s", e)
        return
    logger.debug("LLM service initialized successfully")

    # 1. get all the information about the files

    # 1.1 get all project files
    project_files = get_project_files(config.project_config.working_dir)

    # 1.2 get file type for each project file
    project_files_info: dict[str, dict] = {
        file: {"file_type": get_file_type(config.project_config.working_dir, file)}
        for file in project_files
    }

    # 1.3 get file dependencies for each project file
    await set_files_dependencies(
        config.project_config.working_dir, project_files_info, llm
    )

    # 1.4 build depdency graph
    dependencies_topologically_sorted = create_dependencies_topologically_sorted(
        project_files_info
    )

    logger.info(
        "Analyzed %d files across %d dependency levels",
        len(project_files),
        len(dependencies_topologically_sorted),
    )

    # 2. Create documentation objects

    # 2.1 set file doc type for each project file
    for file_info in project_files_info.values():
        set_file_doc_type(file_info)

    # 2.2 extract entities from each project file

    await asyncio.gather(
        *[
            identify_entities(
                config.project_config.working_dir,
                file,
                project_files_info[file],
                llm,
                cache,
            )
            for file in project_files
        ]
    )

    def default(obj):
        return str(obj)  # or list(obj) if order doesn't matter

    print(json.dumps(project_files_info, indent=4, default=default))

    # 2.3 count how many entities / files / packages we have to document for progress bar.
    # A "package" is a directory that directly contains at least one documentable file.
    # Ancestor directories that only pass through to a single child package are excluded.

    total_entities = sum(
        len(file_info.get("entities", [])) for file_info in project_files_info.values()
    )
    total_files = len(project_files)

    # directories that directly contain at least one documentable file
    dirs_with_files: set[str] = set()
    for file, file_info in project_files_info.items():
        if file_info.get("file_doc_type") not in (None, FileDocType.SKIPPED):
            parent = os.path.dirname(file)
            if parent:
                dirs_with_files.add(parent)

    # Pass 1: collect all candidate directories (leaf packages + all ancestors)
    all_dirs: set[str] = set()
    for d in dirs_with_files:
        while d:
            all_dirs.add(d)
            d = os.path.dirname(d)

    # Pass 2: count direct child packages per directory
    direct_child_count: dict[str, int] = {}
    for d in all_dirs:
        parent = os.path.dirname(d)
        if parent and parent in all_dirs:
            direct_child_count[parent] = direct_child_count.get(parent, 0) + 1

    # A directory is a package if it has documentable files or multiple child packages.
    # Single-child ancestors with no own files are passthroughs — skip them.
    packages: dict[str, dict] = {
        d: {"files": [], "sub_packages": []}
        for d in all_dirs
        if d in dirs_with_files or direct_child_count.get(d, 0) > 1
    }

    # Populate direct files (non-skipped only)
    for file, file_info in project_files_info.items():
        parent = os.path.dirname(file)
        if parent in packages and file_info.get("file_doc_type") not in (
            None,
            FileDocType.SKIPPED,
        ):
            packages[parent]["files"].append(file)

    # Populate direct sub-packages
    for pkg_path in packages:
        parent = os.path.dirname(pkg_path)
        if parent in packages:
            packages[parent]["sub_packages"].append(pkg_path)

    total_packages = len(packages)

    # 2.4 document entities and files for each project file

    for file_set in dependencies_topologically_sorted:
        await asyncio.gather(
            *[
                create_file_documentation(
                    config.project_config.working_dir,
                    file,
                    project_files_info[file],
                    llm,
                    cache,
                )
                for file in file_set
            ]
        )

    # 2.5 write package documentation (bottom-up: deepest packages first)
    packages_by_depth: dict[int, list[str]] = defaultdict(list)
    for pkg_path in packages:
        packages_by_depth[pkg_path.count(os.sep)].append(pkg_path)

    for depth in sorted(packages_by_depth.keys(), reverse=True):
        await asyncio.gather(
            *[
                document_package(
                    config.project_config.working_dir,
                    pkg_path,
                    packages[pkg_path],
                    llm,
                    cache,
                )
                for pkg_path in packages_by_depth[depth]
            ]
        )

    # 2.6 write project documentation
    project_name = os.path.basename(config.project_config.working_dir)
    top_level_packages = [p for p in packages if os.path.dirname(p) not in packages]
    await document_project(
        config.project_config.working_dir,
        project_name,
        top_level_packages,
        llm,
        cache,
    )

    # 3. write the documentation in human readable format
    write_markdown_docs(
        config.project_config.working_dir,
        project_name,
        packages,
        project_files_info,
        cache,
    )

    return
