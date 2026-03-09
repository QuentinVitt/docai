import logging

from docai.config.loader import Config
from docai.deps.base import (
    create_dependencies_topologically_sorted,
    set_files_dependencies,
)
from docai.scanning.file_infos import get_file_type
from docai.scanning.project_infos import get_project_files

logger = logging.getLogger("docai_project")


async def run(config: Config):
    logger.info("Documenting %s", config.project_args.working_dir)

    # 1. get all the information about the files

    # get all project files
    project_files: set[str] = get_project_files(config.project_args.working_dir)
    project_files_info: dict[str, dict] = {
        file: {"file_type": get_file_type(file)} for file in project_files
    }

    # TODO: build LLMService from config.llm_args and pass as llm=
    # add dependent files to project files
    await set_files_dependencies(project_files_info)

    # Extract dependencies
    dependencies_topologicaly_sorted = create_dependencies_topologically_sorted(
        project_files_info
    )


# 2. Create documentation objects

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
