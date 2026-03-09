from docai.documentation.datatypes import DocItemType
from docai.llm.service import LLMService


def document_entity(
    file: str,
    file_info: dict,
    llm: LLMService,
    entity_name: str,
    entity_type: DocItemType,
    entity_parent: str | None,
):

    # prepare prompt based on file and entity type
    file_doc_type = file_info.get("doc_type")
    match file_doc_type, entity_type:
        case 'code', 'function':
            # implement function that returns a DocItem
            raise NotImplementedError("Function documentation is not supported for code files")
        case 'code', 'method':
            raise NotImplementedError("Method documentation is not supported for code files")
        case 'code', 'class':
            raise NotImplementedError("Class documentation is not supported for code files")
        case 'code', 'datatype':
            raise NotImplementedError("Datatype documentation is not supported for code files")
        case 'code', 'constant':
            raise NotImplementedError("Constant documentation is not supported for code files")
        case 'config', 'datatype':
            raise NotImplementedError("Datatype documentation is not supported for config files")
        case 'config', 'constant':
            raise NotImplementedError("Constant documentation is not supported for config files")
        case _:
            raise ValueError(f"Unsupported entity type for {file_doc_type} files: {entity_type}")

    # generate documentation

    # return DocumentationType

def document_code_function_entity():
    # should get:
    # -> File Documentation of Files it directly depends on if available?
    # -> A Project Tree?
    # The actual file content
    # The entity it should document
    # the output format
    # available functions it should be able to use: get_project_tree, get_directory, get_file_content.
