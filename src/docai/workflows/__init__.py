from docai.config.datatypes import ProjectAction
from docai.workflows.document import run as document

WORKFLOWS = {
    ProjectAction.DOCUMENT: document,
}
