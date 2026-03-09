from typing import Optional

from docai.documentation.datatypes import DocItemType, FileDocType
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


async def create_file_documentation(
    file: str, file_info: dict, llm: Optional[LLMService]
):
    # Agent tasks:
    # 1. Identify all entities in the file
    # 2. For each entity: generate documentation
    # 3. generate documentation for the file
    # Agent abilities:
    # - read files
    # - get project structure/tree
    # - get file/function/method/etc. documentation when available

    # 1. Identify doc file type
    file_type = file_info.get("file_type", "unknown")
    file_info["doc_type"] = file_type_map.get(file_type)

    # 2. Get entities from the file
    entities: list[tuple[str, DocItemType, str | None]] = await get_entities(
        file, file_info, llm
    )

    # 3. Generate documentation for each entity
    for entity_name, entity_type, entity_parent in entities:
        pass

    # 4. Generate documentation for the file
