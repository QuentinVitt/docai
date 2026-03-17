import asyncio
import json
import logging
import os

from docai.config.datatypes import Config
from docai.deps.base import (
    create_dependencies_topologically_sorted,
    set_files_dependencies,
)
from docai.documentation.base import identify_entities, set_file_doc_type
from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import FileDocType
from docai.llm.errors import LLMError
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_type
from docai.scanning.project_infos import get_project_files

logger = logging.getLogger(__name__)


async def run(config: Config):
    logger.info("Documenting %s", config.project_config.working_dir)
    # 0.1 set up llm service
    try:
        llm: LLMService = await LLMService.create(config.llm_config)
    except LLMError as e:
        logger.error("Could not initialize LLM service: %s", e)
        return
    logger.debug("LLM service initialized successfully")

    # 0.2 set up documentation cache
    cache = DocumentationCache(
        config.project_config.documentation_cache, config.project_config.working_dir
    )

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
    packages = {
        d for d in all_dirs
        if d in dirs_with_files or direct_child_count.get(d, 0) > 1
    }

    total_packages = len(packages)

    # 2.4 document entities and files for each project file


    for file_set in dependencies_topologically_sorted:
        ...


    return

    # for file_set in dependencies_topologicaly_sorted:
    #     # 2.1 get doc file types

    #     await asyncio.gather(
    #         *[
    #             create_file_documentation(
    #                 config.project_config.working_dir,
    #                 file,
    #                 project_files_info[file],
    #                 llm,
    #                 cache,
    #             )
    #             for file in file_set
    #         ]
    #     )
    #     break

    # def default(obj):
    #     return str(obj)  # or list(obj) if order doesn't matter

    # print(json.dumps(project_files_info, indent=4, default=default))

    # 2.3 generate file/entity documentation with dependencies topological sorted

    # 2.3.1 generate entity documentation

    # 2.3.2 generate file documentation

    # 2.4 generate package documentations

    # 2.5 generate project documentation


# 2. Create documentation objects
# save documentation in cache but also get those no longer needed into disk

# document Objects internal representation
# for files in dependencie_list:
# build async generator for the prompts
# stream the doc results and save them in the cache
# we first need to think about how we want to represent the documentation internally:
# first: divide between files: each file gets its own documentation file. In this file we have different sections for different documentations
#

# doc: name, type, the actuall documentation: input, output, brief description, side_effects that can be triggered etc.


# write interal documentation presentation into external representation.


# The documentation Dataclass:
