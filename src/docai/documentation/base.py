from docai.documentation.cache import DocumentationCache
from docai.documentation.datatypes import DocItemRef, DocItemType, FileDocType
from docai.documentation.entity_documentation import document_entity
from docai.documentation.entity_extraction import get_entities
from docai.llm.service import LLMService

file_type_map: dict[str, FileDocType] = {
    # --- Code ---
    "py": FileDocType.CODE,
    "js": FileDocType.CODE,
    "ts": FileDocType.CODE,
    "jsx": FileDocType.CODE,
    "tsx": FileDocType.CODE,
    "java": FileDocType.CODE,
    "c": FileDocType.CODE,
    "cpp": FileDocType.CODE,
    "h": FileDocType.CODE,
    "hpp": FileDocType.CODE,
    "cs": FileDocType.CODE,
    "go": FileDocType.CODE,
    "rs": FileDocType.CODE,
    "rb": FileDocType.CODE,
    "swift": FileDocType.CODE,
    "kt": FileDocType.CODE,
    "sh": FileDocType.CODE,
    "bash": FileDocType.CODE,
    "ps1": FileDocType.CODE,
    "sql": FileDocType.CODE,
    "r": FileDocType.CODE,
    "scala": FileDocType.CODE,
    "lua": FileDocType.CODE,
    "dart": FileDocType.CODE,
    "ex": FileDocType.CODE,
    "exs": FileDocType.CODE,
    "erl": FileDocType.CODE,
    "hs": FileDocType.CODE,
    "clj": FileDocType.CODE,
    "pl": FileDocType.CODE,
    # --- Config ---
    "yaml": FileDocType.CONFIG,
    "yml": FileDocType.CONFIG,
    "json": FileDocType.CONFIG,
    "toml": FileDocType.CONFIG,
    "ini": FileDocType.CONFIG,
    "cfg": FileDocType.CONFIG,
    "conf": FileDocType.CONFIG,
    "env": FileDocType.CONFIG,
    "properties": FileDocType.CONFIG,
    # --- Docs ---
    "md": FileDocType.DOCS,
    "rst": FileDocType.DOCS,
    # --- Other (human-authored data) ---
    "csv": FileDocType.OTHER,
    "tsv": FileDocType.OTHER,
    # --- Skipped (binary, generated, media, archives) ---
    "pdf": FileDocType.SKIPPED,
    "doc": FileDocType.SKIPPED,
    "docx": FileDocType.SKIPPED,
    "xls": FileDocType.SKIPPED,
    "xlsx": FileDocType.SKIPPED,
    "ppt": FileDocType.SKIPPED,
    "pptx": FileDocType.SKIPPED,
    "jpg": FileDocType.SKIPPED,
    "jpeg": FileDocType.SKIPPED,
    "png": FileDocType.SKIPPED,
    "gif": FileDocType.SKIPPED,
    "bmp": FileDocType.SKIPPED,
    "tiff": FileDocType.SKIPPED,
    "webp": FileDocType.SKIPPED,
    "mp3": FileDocType.SKIPPED,
    "wav": FileDocType.SKIPPED,
    "mp4": FileDocType.SKIPPED,
    "mov": FileDocType.SKIPPED,
    "avi": FileDocType.SKIPPED,
    "zip": FileDocType.SKIPPED,
    "tar": FileDocType.SKIPPED,
    "gz": FileDocType.SKIPPED,
    "rar": FileDocType.SKIPPED,
    "7z": FileDocType.SKIPPED,
    "pyc": FileDocType.SKIPPED,
    "class": FileDocType.SKIPPED,
    "exe": FileDocType.SKIPPED,
    "dll": FileDocType.SKIPPED,
    "so": FileDocType.SKIPPED,
    "dylib": FileDocType.SKIPPED,
    "whl": FileDocType.SKIPPED,
    "lock": FileDocType.SKIPPED,
    "log": FileDocType.SKIPPED,
}


def set_file_doc_type(file_info: dict):
    file_type = file_info.get("file_type", "unknown")
    file_info["file_doc_type"] = file_type_map.get(file_type)


async def identify_entities(
    project_path: str,
    file: str,
    file_info: dict,
    llm: LLMService,
    cache: DocumentationCache,
):

    # 1. Check cache first
    file_doc = cache.get_file_documentation(file)
    if file_doc:
        file_info["entities"] = file_doc.items

    # 2. Generate entities if not in cache
    entities: list[DocItemRef] = await get_entities(project_path, file, file_info, llm)

    file_info["entities"] = entities


async def create_file_documentation(
    project_path, file: str, file_info: dict, llm: LLMService, cache: DocumentationCache
):
    # Agent tasks:
    # 1. Identify all entities in the file
    # 2. For each entity: generate documentation
    # 3. generate documentation for the file
    # Agent abilities:
    # - read files
    # - get project structure/tree
    # - get file/function/method/etc. documentation when available

    # 3. Generate documentation for each entity
    for entity in file_info["entities"]:
        doc_item = await document_entity(
            project_path,
            file,
            file_info,
            entity_name,
            entity_type,
            entity_parent,
            llm,
            cache,
        )
        print(doc_item)
    return

    # 4. Generate documentation for the file
