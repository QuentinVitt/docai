"""
Calls an LLM with a file to determine which other project files it depends on.
Used as a fallback when no language-specific extractor is available.
"""

from docai.llm.service import LLMService

_SYSTEM_PROMPT = """\
You are an expert code analyst. Your task is to identify which files in a \
software project a given source file directly depends on — meaning files it \
imports, includes, or otherwise references at the source level.

Rules:
- Only return files that appear in the provided project file list.
- Do not include standard library modules or third-party packages.
- Only include direct dependencies (files this file itself references, not \
transitive ones).
- If there are no project-internal dependencies, return an empty list.\
"""


async def extract_dependencies(
    file: str,
    file_content: str,
    file_type: str | None,
    all_files: set[str],
    llm: LLMService,
) -> set[str]:

    file_list_str = "\n".join(f for f in all_files if f != file)
    lang = file_type if file_type else "unknown"

    prompt = f"""\
Identify the project-internal dependencies of the following file.

<file>
Path: {file}
Type: {lang}
</file>

<project_files>
Only return dependencies whose paths appear in this list:
{file_list_str}
</project_files>

<file_content>
```{lang}
{file_content}
```
</file_content>

Return the file paths exactly as they appear in the project_files list.\
"""

    structured_output = {
        "type": "object",
        "required": ["dependencies"],
        "properties": {
            "dependencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "File paths of project-internal files that this file directly "
                    "depends on. Each entry must exactly match a path from the "
                    "provided project file list."
                ),
            }
        },
        "additionalProperties": False,
    }

    result, _ = await llm.generate(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        structured_output=structured_output,
    )

    if isinstance(result, dict):
        return set(result.get("dependencies", []))
    raise ValueError("Unexpected result type: " + str(type(result)))
