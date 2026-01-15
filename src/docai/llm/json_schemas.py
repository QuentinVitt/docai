from typing import List

from pydantic import BaseModel, Field


class File(BaseModel):
    name: str = Field(description="Name of the file.")
    path: str = Field(description="relative path to the file.")


class extract_dependencies_output(BaseModel):
    file: File = Field(description="File containing the extracted dependencies.")
    dependencies: List[File] = Field(
        description="List of files in this project that this file depends on."
    )


extract_dependencies_output_schema = extract_dependencies_output.model_json_schema()
