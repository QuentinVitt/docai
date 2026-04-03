# ADR-008: Structure Extractor Component Design

## Status
Accepted

## Context
ADR-006 established the Structure Extractor as the second pipeline component — responsible for
analyzing individual source files to produce entity directories and resolved dependencies.
ADR-003 defined three extraction paths (clean tree-sitter, error-verified tree-sitter, full
LLM fallback). ADR-004 defined the entity taxonomy (Callable, Type, Value, Module,
Implementation). ADR-007 defined the file manifest that serves as the Structure Extractor's
input alongside the source file.

This ADR defines the internal architecture of the Structure Extractor: how tree-sitter and
LLM extraction paths are organized, how language-specific knowledge is structured, how import
resolution works per language, and which languages receive dedicated tree-sitter support in v1.

### Key design tensions

- **Universality vs. optimization**: docai must work for any language (via LLM), but
  frequently-used languages benefit enormously from tree-sitter (free, fast, deterministic).
  The architecture must treat LLM as the fully capable default and tree-sitter as an
  accelerator — not the other way around.
- **Language-specific knowledge**: Entity extraction, import extraction, and import resolution
  all require language-specific logic. This knowledge must be organized so that adding a new
  language is a data/config task, not a code restructuring task.
- **Scope boundary with config files**: Only source code files go through the Structure
  Extractor. Code-like configuration files (Dockerfiles, Makefiles, CI configs) bypass entity
  extraction entirely and go directly to the Documentation Generator for module-level
  summarization.

## Options Considered

### Internal organization of language-specific knowledge

#### Option A: Language-specific strategy classes
A base interface defines `extract_entities()`, `extract_imports()`, and `resolve_imports()`.
Each supported language provides a class implementing all three. The LLM fallback is another
strategy class.
- **Pros**: Clean OOP design, each language fully encapsulated, maximum flexibility for
  unusual language patterns
- **Cons**: Class-per-language hierarchy is heavy for a solo developer. Adding a language
  means creating a new class with boilerplate. Over-engineered for v1 when most languages
  have similar extraction patterns.

#### Option B: Generic extraction with language configuration tables
One extraction algorithm parameterized by per-language configuration: a table mapping AST
node types to entity categories, a table mapping import node types to extraction patterns,
and a set of resolution heuristics. Adding a new language means adding configuration entries.
- **Pros**: Less code to maintain, adding a language is a data task, shared extraction logic
  means bugs are fixed once. Easier for a solo developer.
- **Cons**: Less flexible for languages with truly unusual patterns that can't be captured
  in a table. May need escape hatches for edge cases.

### Design philosophy

#### Option A: Tree-sitter as primary, LLM as fallback
Tree-sitter is the default path; LLM only activates when no grammar exists.
- **Pros**: Maximizes deterministic extraction for supported languages
- **Cons**: The LLM path becomes second-class — less tested, less reliable. The majority of
  languages (those without tree-sitter configs) get inferior treatment. If tree-sitter configs
  are the bottleneck for language support, adoption is gated by config development.

#### Option B: LLM as the capable default, tree-sitter as accelerator
The LLM path is designed to be fully capable and well-tested for any language. Tree-sitter
configs exist purely as an optimization (faster, cheaper, deterministic) for high-frequency
languages.
- **Pros**: Every language gets the same quality baseline. Tree-sitter support is a bonus,
  not a requirement. The LLM path gets serious investment because unsupported languages
  depend on it entirely. Adding tree-sitter support for a new language is purely additive —
  it doesn't change the fallback behavior.
- **Cons**: The LLM path must be robust, which requires careful prompt design and output
  validation. LLM extraction is slower and costs money.

## Decision

### Design philosophy

**LLM as the capable default, tree-sitter as accelerator** (Option B). The LLM extraction
path is the universal baseline — designed, tested, and maintained as a first-class path. It
works for any language the LLM understands, which in practice means every mainstream and most
niche programming languages. Tree-sitter language configs are optimizations layered on top
for high-frequency languages, providing speed, zero cost, and determinism.

This means:
- The LLM extraction prompt and output parsing are the most critical pieces to get right
- Every language, whether tree-sitter-supported or not, produces the same FileAnalysis output
- Adding tree-sitter support for a new language never changes the LLM fallback behavior
- The LLM path is the one exercised by the most languages, so it gets the most real-world
  testing

### Internal organization

**Generic extraction with language configuration tables** (Option B). Per-language knowledge
is expressed as configuration, not code:

Each tree-sitter language config contains:

**Entity mapping table** — maps AST node types to universal entity categories:
```
python:
  function_definition → Callable
  class_definition → Type
  assignment (module-level) → Value
  decorated_definition → unwrap, apply decorator as complexity modifier

javascript:
  function_declaration → Callable
  arrow_function (assigned) → Callable
  class_declaration → Type
  lexical_declaration (const, module-level) → Value
  export_statement → visibility marker
```

**Import pattern table** — defines which AST node types represent imports and how to extract
the raw import string:
```
python:
  import_statement → extract module name
  import_from_statement → extract module name from "from" clause

javascript:
  import_statement → extract source string literal
  call_expression (require) → extract argument string literal

rust:
  use_declaration → extract path
  mod_item → extract module name
```

**Resolution heuristics** — language-specific rules for mapping raw import strings to project
files (see Import Resolution section below).

**Visibility rules** — how to determine if an entity is public or private:
```
python: _prefix → private, no prefix → public
rust: pub keyword → public, no pub → private
javascript: export keyword → public, no export → private
go: uppercase first letter → exported, lowercase → unexported
java: public/private/protected keywords
c/cpp: header file presence as public API indicator
```

A single generic AST walker consumes these tables to perform extraction. Language-specific
edge cases that can't be captured in tables are handled by optional per-language hook functions
— small, focused functions that handle the exceptional cases without requiring a full strategy
class.

### v1 tree-sitter language set

Six languages (plus their variants) receive dedicated tree-sitter configs in v1:

| Language | Variants | Rationale |
|----------|----------|-----------|
| **Python** | .py, .pyi | Implementation language, first test case |
| **JavaScript / TypeScript** | .js, .jsx, .ts, .tsx, .mjs, .cjs | Largest ecosystem, most users |
| **Rust** | .rs | Exercises Implementation entity category (trait impls), systems language validation |
| **Go** | .go | Popular systems language, simple module system |
| **Java** | .java | Massive enterprise usage, exercises OOP patterns (interfaces, annotations) |
| **C / C++** | .c, .h, .cpp, .hpp, .cc, .cxx | Foundational, exercises struct/macro/header patterns, shared grammar structure |

TypeScript and JavaScript are separate configs that share common patterns. TypeScript adds
type annotations, interfaces, enums, and generics that JavaScript lacks.

C and C++ share significant grammar overlap but are separate configs. C++ adds classes,
namespaces, templates, and inheritance that C lacks.

All other languages use the LLM extraction path. This covers the vast majority of real-world
projects — these six languages (with variants) account for a large percentage of actively
maintained open source and commercial codebases.

### Scope boundary: source code only

The Structure Extractor processes only files classified as **source code** by File Discovery
(ADR-007). Code-like configuration files (Dockerfiles, Makefiles, CI configs, docker-compose,
Terraform, SQL migrations) bypass the Structure Extractor entirely. They have no entity
directory and no resolved dependencies. They proceed directly to the Documentation Generator,
which produces a module-level summary using the LLM.

Shell scripts (.sh, .bash) are treated as source code if discovered as such, but do not
receive a dedicated tree-sitter config in v1. They use the LLM extraction path.

### FileAnalysis output contract

Both extraction paths (tree-sitter and LLM) produce the same output:

```
FileAnalysis:
  file_path: str              # relative path from project root
  entities:                    # list of extracted entities
    - category: str            # Callable | Type | Value | Implementation
      name: str                # entity name
      signature: str           # full signature (e.g., "def parse(content: str) -> Document")
      line_start: int          # first line of entity
      line_end: int            # last line of entity
      visibility: str          # public | private | internal
      decorators: list[str]    # decorator/annotation names (if any)
      parent: str | null       # enclosing entity name (for methods inside classes)
  dependencies:                # list of resolved project file dependencies
    - str                      # relative path of dependency file
  raw_imports:                 # preserved for debugging and diagnostics
    - import_string: str       # raw import as it appears in source
      resolved_to: str | null  # resolved project file path, or null if external
  parse_errors: bool           # true if tree-sitter found ERROR nodes
  extraction_method: str       # tree-sitter | llm-verified | llm-fallback
```

The Module entity category (from ADR-004) is not extracted — it represents the file itself
and is created implicitly during documentation generation.

`raw_imports` is preserved alongside `dependencies` for diagnostics. When an import resolves
incorrectly, inspecting the raw string and its resolution aids debugging. The `dependencies`
list (resolved paths only, external imports excluded) is what the Graph Builder consumes.

### Extraction flow

```
Input: source file + file manifest
    │
    ├─ Tree-sitter config exists for this language?
    │     │
    │     ├─ YES: Parse with tree-sitter
    │     │    │
    │     │    ├─ No ERROR nodes
    │     │    │    → Extract entities via config tables
    │     │    │    → Extract raw imports via config tables
    │     │    │    → Resolve imports against file manifest
    │     │    │    → Return FileAnalysis (method: tree-sitter)
    │     │    │
    │     │    └─ ERROR nodes present
    │     │         → Extract entities via config tables (best-effort)
    │     │         → LLM verification of entity directory (ADR-003)
    │     │         → Merge corrections into entity directory
    │     │         → Extract raw imports via config tables
    │     │         → Resolve imports against file manifest
    │     │         → Return FileAnalysis (method: llm-verified)
    │     │
    │     └─ NO: LLM extraction path
    │          → Send file content + file manifest + entity taxonomy to LLM
    │          → LLM returns entities + resolved dependencies directly
    │          → Validate entity categories against taxonomy
    │          → Validate resolved dependencies against file manifest
    │          → Return FileAnalysis (method: llm-fallback)
    │
    └─ Output: FileAnalysis (uniform regardless of path taken)
```

### Import resolution

Import resolution maps raw import strings to project files. The approach differs by
extraction path:

**Tree-sitter path**: Raw import strings are extracted from the AST, then resolved against
the file manifest using per-language heuristics.

**LLM path**: The LLM receives the file manifest as context and returns resolved project
file paths directly. No separate resolution step needed.

#### Per-language resolution heuristics (tree-sitter path)

Each language has a small, self-contained resolution function (roughly 20-30 lines) that
implements the language's import conventions:

**Python**:
- `from docai.parser import X` → split on dots → try `docai/parser.py` and
  `docai/parser/__init__.py` against manifest
- `from .sibling import Y` → resolve `.` relative to current file's directory
- `from ..parent import Z` → resolve `..` relative to current file's parent
- `import os` → no match in manifest → external, skip
- Ambiguity rule: if `parser` matches both a project file and could be a stdlib module,
  match against manifest first (matches Python's own resolution: local takes precedence)

**JavaScript / TypeScript**:
- `import { X } from './parser'` → relative path, try appending `.js`, `.ts`, `.tsx`,
  `.jsx`, `/index.js`, `/index.ts`
- `import { Y } from 'lodash'` → no `./` or `../` prefix → external, skip
- `require('../utils')` → same relative resolution as import statements
- Path aliases (e.g., `@/components/`) → not resolved in v1 (would require reading
  tsconfig.json); treated as external

**Rust**:
- `use crate::parser::X` → `crate::` maps to `src/`, resolve `parser` to `src/parser.rs`
  or `src/parser/mod.rs`
- `use super::sibling` → resolve relative to current file's parent module
- `use self::child` → resolve relative to current file's module
- `mod tests;` → look for `tests.rs` in same directory or `tests/mod.rs`
- `use std::collections` → no `crate::`, `super::`, or `self::` prefix and not a `mod`
  declaration → external, skip

**Go**:
- `import "myproject/internal/parser"` → strip the module prefix (from go.mod), map
  remaining path to directory, match against manifest
- `import "fmt"` → no module prefix match → external, skip
- Go files in the same directory are implicitly in the same package — this is captured
  at the directory level, not per-import

**Java**:
- `import com.myproject.parser.Parser` → map package path to directory structure
  (`com/myproject/parser/`), find `Parser.java` in that directory
- `import java.util.List` → no match against project package prefix → external, skip
- Package prefix determined by scanning project structure for common root package

**C / C++**:
- `#include "parser.h"` → quoted includes are project-relative, resolve against manifest
  (try relative to current file first, then project root)
- `#include <stdio.h>` → angle-bracket includes → external, skip
- `#include "subdir/helper.h"` → resolve path relative to current file or project root

#### Resolution validation

All resolved dependencies are validated against the file manifest. A resolution is only
accepted if the target file exists in the manifest and is classified as source code or
code-like config. This prevents phantom dependencies from typos or stale imports.

Unresolvable project-looking imports (e.g., a relative path that doesn't match any file) are
logged as warnings in the FileAnalysis for diagnostic purposes but excluded from the
dependency list.

### LLM extraction prompt design

The LLM extraction path receives:

1. **File content** — full source code of the file
2. **File path** — relative path from project root (provides context about the file's role)
3. **File manifest** — list of all project file paths (the universe of valid dependency
   targets)
4. **Entity taxonomy** — the five universal categories from ADR-004 with examples

The LLM is asked to return structured output containing:
- Entities with category, name, signature, line range, visibility
- Resolved project file dependencies (matched against the provided file manifest)
- Indication of any uncertainty or ambiguity

The prompt explicitly instructs the LLM to:
- Only return dependency paths that exist in the provided file manifest
- Classify entities using only the five taxonomy categories
- Mark visibility based on the language's conventions
- Distinguish between internal imports (matched to manifest) and external imports (skipped)

LLM output is validated before being accepted:
- Entity categories must be one of the five taxonomy values
- Resolved dependency paths must exist in the file manifest
- Line ranges must fall within the file's actual line count
- Any validation failure triggers a warning, and the invalid entry is excluded

### LLM verification prompt design (error path)

When tree-sitter parsing produces ERROR nodes, the verification call receives:

1. **Entity directory as extracted by tree-sitter** — entity names, categories, line ranges
2. **Full source code** — so the LLM can compare against the actual code
3. **Focused question**: Are any entities missing? Are any listed entities actually multiple
   entities merged together? Are any entity boundaries (line ranges) incorrect?

The LLM returns only corrections — not a full entity list. This keeps the call cheap and
focused. Corrections are merged into the tree-sitter entity directory before producing the
final FileAnalysis.

Import extraction and resolution still use the tree-sitter path (import nodes are less
susceptible to structural damage from parse errors than entity boundaries).

## Consequences

### Positive
- LLM-first philosophy ensures every language gets capable extraction, not just the six
  with tree-sitter configs
- Tree-sitter configs as acceleration mean adding language support is purely additive —
  it improves speed and cost without changing behavior
- Configuration tables make adding a new tree-sitter language a data task, not a code
  restructuring task
- Per-language import resolution heuristics are small, self-contained, and independently
  testable
- The FileAnalysis output contract is uniform regardless of extraction path — downstream
  components don't know or care how extraction happened
- Raw imports preserved alongside resolved dependencies support debugging when resolution
  goes wrong
- LLM output validation prevents bad data from entering the pipeline (unrecognized entity
  categories, phantom dependencies, invalid line ranges)

### Negative / Trade-offs accepted
- Six tree-sitter language configs is significant v1 scope. Each needs entity mapping,
  import extraction, resolution heuristics, and testing. Mitigation: start with Python
  (the implementation language), validate the config table approach, then add the remaining
  five incrementally.
- Language config tables may not capture every edge case. Hook functions provide an escape
  hatch but add a secondary code path per language. In practice, edge cases are rare enough
  that this is manageable.
- The LLM extraction path costs money and time per file. For large projects in unsupported
  languages, this could be expensive. Mitigation: caching (via Project State) means each
  file is only extracted once unless it changes.
- Import resolution heuristics will have false positives and negatives, especially for
  languages with complex module systems (Python's namespace packages, TypeScript's path
  aliases, Java's classpath). The manifest-first matching approach is correct for the common
  case; edge cases produce warnings rather than silent failures.
- TypeScript path aliases (`@/components/`) and similar build-tool-configured import
  rewriting are not supported in v1. These would require reading tsconfig.json or similar
  config files, adding significant complexity. Treated as external imports for now.

### Constraints created
- Need to design the language config table schema (formal structure for entity mappings,
  import patterns, resolution heuristics, visibility rules)
- Need to design the LLM extraction prompt and validate it against multiple languages
- Need to design the LLM verification prompt (error path) and validate correction merging
- Need to define the hook function interface for language-specific edge cases
- Need to establish a testing strategy: for each tree-sitter-supported language, a set of
  test files covering entity types, import patterns, and resolution edge cases

## Open Questions

1. **LLM output format**: Should the LLM extraction prompt request JSON, YAML, or a custom
   structured format? JSON is easiest to parse but the LLM may produce invalid JSON. YAML
   is more forgiving. A custom format with clear delimiters might be most reliable. Needs
   experimentation.

2. **Config table extensibility**: Should third-party contributors be able to add language
   configs as plugins (separate files/packages), or is adding them to the main codebase
   sufficient for now? Plugin architecture adds complexity but enables community contributions
   without forking.

3. **Entity extraction depth for nested structures**: How deep does extraction go for nested
   entities? A class containing methods — do we extract the methods as separate entities with
   a `parent` reference, or only extract the class? Current design extracts both (methods are
   Callables with `parent` set to the class name). But what about nested classes, inner
   functions, closures? A depth limit may be needed.

4. **Tree-sitter grammar installation**: Decided — **bundle all v1 grammars with the
   package.** Pre-compiled grammar bindings ship as regular Python dependencies. Total
   overhead is a few megabytes (each grammar is ~200-500KB), negligible for a CLI tool
   that makes LLM API calls. User experience of `pip install docai` with everything
   working immediately outweighs the package size cost. Future language additions beyond
   v1 can be bundled in subsequent releases or offered as optional extras.
