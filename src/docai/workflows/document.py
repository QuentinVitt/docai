import json
import logging

from docai.config.datatypes import Config
from docai.deps.base import (
    create_dependencies_topologically_sorted,
    set_files_dependencies,
)
from docai.llm.errors import LLMError
from docai.llm.service import LLMService
from docai.scanning.file_infos import get_file_type
from docai.scanning.project_infos import get_project_files

logger = logging.getLogger(__name__)


async def run(config: Config):
    logger.info("Documenting %s", config.project_config.working_dir)
    # 0. set up llm service
    try:
        llm: LLMService = await LLMService.create(config.llm_config)
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
    dependencies_topologicaly_sorted = create_dependencies_topologically_sorted(
        project_files_info
    )

    logger.info(
        "Analyzed %d files across %d dependency levels",
        len(project_files),
        len(dependencies_topologicaly_sorted),
    )

    # 2. Create documentation objects

    # 2.1 get doc file types

    # 2.2 extract entity list

    # 2.3 generate file/entity documentation with dependencies topological sorted

    # 2.3.1 generate entity documentation

    # 2.3.2 generate file documentation

    # 2.4 generate package documentations

    # 2.5 generate project documentation

    return


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
