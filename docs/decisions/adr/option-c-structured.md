---
file: src/parser.py
module_purpose: Markdown parsing — converts raw markdown into structured Document objects
depends_on:
  - file: src/models.py
    imports: [Document, Section, CodeBlock]
  - file: src/config.py
    imports: [ParserConfig]
  - file: src/errors.py
    imports: [ParseError]
entities:
  classes: [MarkdownParser]
  public_functions: []
  private_functions: []
generated: 2026-03-25T14:30:00Z
source_hash: a1b2c3d4e5f6
---

# src/parser.py

Provides markdown parsing capabilities, converting raw markdown text into structured `Document`
objects with hierarchical sections and extracted code blocks.

## MarkdownParser

| Property | Value |
|----------|-------|
| Type | Class |
| Constructor args | `config: ParserConfig` |
| Public methods | `parse_file`, `parse_string` |
| Internal methods | `_extract_sections`, `_build_hierarchy`, `_extract_code_blocks` |

A parser that converts markdown content into structured document representations.

### parse_file

| Property | Value |
|----------|-------|
| Signature | `parse_file(path: Path) -> Document` |
| Visibility | Public |
| Calls | `parse_string` |
| Called by | *(requires cross-file analysis)* |

Reads a file from disk and parses its markdown content into a `Document`. Delegates to
`parse_string` after reading the file using the configured encoding.

### parse_string

| Property | Value |
|----------|-------|
| Signature | `parse_string(content: str, source: Optional[Path] = None) -> Document` |
| Visibility | Public |
| Calls | `_extract_sections`, `_extract_code_blocks` |
| Called by | `parse_file` |

Core parsing method. Runs section extraction and code block extraction independently, then
combines results into a `Document`.

### _extract_sections

| Property | Value |
|----------|-------|
| Signature | `_extract_sections(content: str) -> list[Section]` |
| Visibility | Internal |
| Calls | `_build_hierarchy` |
| Called by | `parse_string` |

Finds ATX-style markdown headings via regex, creates flat `Section` objects, then delegates
to `_build_hierarchy` for nesting. Does not support setext-style headings.

### _build_hierarchy

| Property | Value |
|----------|-------|
| Signature | `_build_hierarchy(flat_sections: list[Section]) -> list[Section]` |
| Visibility | Internal |
| Calls | — |
| Called by | `_extract_sections` |

Stack-based algorithm that converts a flat list of sections into a nested tree based on heading
levels. Each section becomes a child of the nearest preceding section with a lower heading level.

### _extract_code_blocks

| Property | Value |
|----------|-------|
| Signature | `_extract_code_blocks(content: str) -> list[CodeBlock]` |
| Visibility | Internal |
| Calls | — |
| Called by | `parse_string` |

Extracts triple-backtick fenced code blocks with optional language identifiers. Does not handle
indented code blocks or nested fences.
