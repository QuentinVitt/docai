from docai.documentation.datatypes import DocItemType
from docai.llm.service import LLMService

_SYSTEM_PROMPT_CODE_ENTITIES = (
    "You are an expert code analyst. Identify all documentable top-level entities "
    "in a source file: public functions, classes, methods, datatypes, and "
    "module-level constants. Skip imports, local variables, and private helpers."
)

_STRUCTURED_OUTPUT_CODE_ENTITIES: dict = {
    "type": "object",
    "required": ["entities"],
    "additionalProperties": False,
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["function", "method", "class", "datatype", "constant"],
                    },
                },
            },
        }
    },
}


async def get_enties_extraction_code_file_prompt(
    file: str, file_type: str | None, file_content: str
) -> str:
    prompt = f"""\
Identify all documentable entities in the following {file_type if file_type else ""} source file.

Entity types:
- function : standalone callable, not inside a class
- method   : callable defined inside a class
- class    : class or interface definition
- datatype : data structure type (dataclass, TypedDict, struct, enum, etc.)
- constant : module-level named constant (e.g. MAX_SIZE = 100)

Rules:
- Skip imports, local variables, and private/internal helpers (names starting with _).
- Skip ALL dunder methods (__init__, __str__, etc.) — they are handled separately
  when documenting the class itself.
- List each method separately from its class.

<file>
Path: {file}
Language: {file_type if file_type else "unknown"}
</file>

<file_content>
```{file_type if file_type else "unknown"}
{file_content}
```
</file_content>

<examples>
Input (Python):
    MAX_RETRIES = 3

    class UserService:
        def __init__(self, db): ...
        def get_user(self, user_id: int): ...
        def _build_query(self): ...  # private — skip

    def format_name(first: str, last: str) -> str: ...

Output:
    [{{"name": "MAX_RETRIES",  "type": "constant"}},
     {{"name": "UserService",  "type": "class"}},
     {{"name": "get_user",     "type": "method"}},
     {{"name": "format_name",  "type": "function"}}]
</examples>
"""
    return prompt
