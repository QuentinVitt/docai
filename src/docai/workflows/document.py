import logging

from docai.config.loader import Config
from docai.deps.base import create_dependencies_list

logger = logging.getLogger('docai_project')

def run(config: Config):
    logger.info('Documenting %s', config.project_args.working_dir)

    # Maybe first a check if that is even a programming project? We don't want to work on documenting a project that is not even a project.

    # Extract dependencies
    # this will return a list of sets of filenames in this project
    dependencie_list = create_dependencies_list(set())

    # document Objects internal representation

    # write interal documentation presentation into external representation.
