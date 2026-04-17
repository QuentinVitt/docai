# docai — Architecture Decision Summary

> **Project**: docai ("one tool to document them all")
> **Purpose**: CLI tool that automatically generates documentation for programming projects using LLMs
> **Date**: March 28, 2026 (updated April 3, 2026 — project structure complete)
> **Phase**: All architecture phases complete, ready for implementation

---

## Project Vision

Developers don't write documentation. When revisiting code — especially code with deep call
chains — understanding what functions do requires tediously reading through every subfunction.
LLMs can write better documentation than most developers if given the right context.

docai is a CLI tool that analyzes a codebase, determines the right context for each piece of
code, and generates high-quality documentation using an LLM. It is language-universal, runs
locally, and produces external documentation files.

### Future vision (out of scope for v1)
- Automated README generation
- Architecture overviews and flowchart generation
- Onboarding assistant: an LLM that walks new developers through a project using the generated
  documentation as a knowledge base (likely via GraphRAG)
- Inline source injection: writing documentation directly into source files using
  language-specific formats (Python docstrings, JSDoc, Rust `///`, etc.)
- `.docaiignore` explicit type annotations (`!file.xyz:python`)
- Monorepo support (independent subgraph detection)
- Streaming Discovery → Extraction pipeline
- Configurable state directory location

---

## Core Domain Decisions

### What gets documented

docai generates documentation at three levels:

| Level | What | Example |
|-------|------|---------|
| **Function/method** (level 2) | Individual callables, types, values | "What does `parse_file` do?" |
| **Module/file** (level 3) | How a file's entities work together | "What is `parser.py` for?" |
| **Package/directory** (level 4) | Entry point overview of a module group | "What does the `parsing/` package provide?" |

Architecture docs (level 5) and project docs like READMEs (level 6) are explicitly future
features. Package summaries are generated for qualifying directories (see Package Rules
below).

### Entity taxonomy

Six universal categories covering all programming paradigms. Each entity carries a **kind**
(freeform string describing the specific variant within the category). Categories keep the
pipeline simple; kind gives the Documentation Generator a hint for template selection.

| Category | What it covers | Extracted |
|----------|---------------|-----------|
| **Callable** | Functions, methods, constructors, closures, generators, predicates, triggers | Yes |
| **Macro** | C preprocessor macros, Rust `macro_rules!`/proc macros, Lisp macros | Yes |
| **Type** | Classes, structs, enums, interfaces, traits, type aliases, unions, records | Yes |
| **Value** | Constants, module-level variables, statics, exports, re-exports | Yes |
| **Module** | Files/modules as organizational units | Implicit (not extracted, created during documentation) |
| **Implementation** | Trait impls, typeclass instances, protocol conformances | Yes (only in languages with syntactically separate implementation blocks) |

Decorators, annotations, and generics are not separate categories — they are visible in
source code and handled by the LLM during documentation generation.

### Entity extraction depth

Entities are extracted at two levels of nesting:
- **Depth 0**: all top-level entities in a file (functions, classes, constants, type aliases,
  macros, etc.)
- **Depth 1**: entities that define a type's interface — methods, constructors, properties,
  enum variants, static members, associated types/constants. These carry a `parent` field
  referencing the enclosing type.

Depth 1 extraction is scoped to **type members**, not arbitrary nesting. A method inside a
class is extracted because it's part of the class's API. A function inside another function
is not extracted because it's an implementation detail.

Not extracted as separate entities:
- Variables inside functions or methods
- Functions defined inside other functions
- Classes defined inside functions
- Any nesting beyond depth 1 (nested classes inside classes, closures inside methods)

These are documented as part of their parent's description when the LLM sees the full source
code during documentation generation.

### Accessor handling

Accessors (getters, setters, properties) are extracted as regular entities with
`category=callable` and an appropriate kind (e.g., `getter`, `setter`, `property`). They are
not folded into the parent Type at extraction time. The Documentation Generator decides
presentation — folding trivial accessors into the parent Type's field documentation, or
documenting complex ones standalone — based on the actual source code. This moves the
complexity/triviality judgment from extraction (where it's hard across languages) to
documentation generation (where the LLM sees the code).

### Documentation depth scaling — LLM-driven

The extraction model carries no complexity signals (no line counts, no roles, no decorators,
no generic type parameter flags). Depth scaling is fully delegated to the LLM during
documentation generation. The LLM assesses complexity from the actual source code and assigns
a complexity rating per entity:

- **trivial** — obvious behavior, one-liner, simple wrapper
- **standard** — normal complexity, per-file documentation is sufficient
- **complex** — non-trivial logic, subtle behavior, qualifies for per-entity follow-up call

Kind and category provide documentation template guidance, not depth rules.

### What is documented about each entity

Documentation output uses a **discriminated union** on category. Each category has
genuinely different documentation fields. The LLM produces structured JSON per category
via Pydantic JSON schemas.

#### Callable

Anything invoked to perform an action or compute a result.

Documentation fields: description (always), parameters (list of name/type/description),
return_value, side_effects (list), error_behavior, example_usage, notes (catch-all list for
async, static, mutates self, yields, thread safety, language-specific concerns), complexity.

#### Macro

Compile-time or preprocessing code generation.

Documentation fields: description (always), input_patterns (list of parameters or match
arms), expansion_description, example_usage, notes, complexity.

#### Type

Anything defining the shape of data or a behavior contract.

Documentation fields: description (always), fields (list of name/type/description), variants
(list of name/description/fields for enums/unions), relationships (extends/implements/
contains), protocol_methods (name list of implemented dunder/protocol methods),
folded_accessors (name list of accessor entities folded into fields), example_usage, notes,
complexity.

Protocol methods with non-obvious behavior are documented standalone as Callables. Trivial
protocol methods appear in the Type's `protocol_methods` list. Completeness verification
checks that every extracted entity is accounted for — either standalone or in a Type's
`protocol_methods` or `folded_accessors` list.

#### Value

Module-level constants, variables, statics, exports.

Documentation fields: description (always), value (actual value for constants/magic numbers),
notes, complexity. Most values will be `complexity=trivial`.

#### Implementation

Syntactically separate connection between a type and a behavior contract.

Documentation fields: description (always), connects (e.g., "Display for AST"),
notable_methods (methods deviating from expectations), notes, complexity.

#### Module

The file itself as an organizational entity. Implicit — produced during documentation
generation as `module_overview` in the file documentation response.

---

## File Type Handling

### File classifications

Five top-level categories determined by the Discovery component's detection stack:

#### Processed

Any file that enters the Structure Extractor. The extraction strategy is determined by the
extraction method map (see below), not by the file classification. Every processed file gets
at minimum a module-level description. Whether it also gets entity-level documentation depends
on what the extractor finds.

After extraction, the file type is determined by the FileAnalysis (lives on FileAnalysis, not
the manifest):

**Source file** — a recognized programming language file. Gets full entity extraction, full
import resolution, entity-level and module-level documentation. Examples: `.py`, `.rs`, `.js`,
`.ts`, `.go`, `.java`, `.c`, `.cpp`, `.rb`, `.swift`, `.kt`, `.cs`, `.hs`, `.ex`.

**Source-like config** — not a programming language, but the extractor found imports to other
project files. No entity extraction — treated as a single Module entity. Imports feed into
the dependency graph. Gets a module-level description only. Examples: `.scss` with `@use`,
HTML template with `{% import %}`, Makefile with `include`.

**Config file** — not a programming language, no imports found. No entity extraction, no
dependencies. Treated as a single Module entity. Gets a module-level description only.
Examples: Dockerfile, `docker-compose.yml`, `.github/workflows/*.yml`, `pyproject.toml`,
`Cargo.toml`, `package.json`, `tsconfig.json`, `.env.example`, plain CSS, Terraform files.

#### Documentation

Existing project documentation. Not processed by the Structure Extractor. Gets a Pass 1
purpose sentence derived from filename and path only (no file content is read during Pass 1).
Mentioned in package summaries. Content is never consumed as context for other files'
documentation to avoid circular reasoning.

Examples: `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/` directory contents,
`.rst` documentation files.

#### Asset

Binary and resource files. Not processed individually. Filenames, types, and counts are
collected per directory in the directory registry and included as context in package summary
generation.

Examples: images (`.png`, `.jpg`, `.svg`, `.gif`, `.webp`), fonts (`.woff`, `.ttf`, `.otf`),
video/audio (`.mp4`, `.mp3`, `.wav`), PDFs, databases (`.db`, `.sqlite`), data fixtures
(`.csv` datasets, `.json` test fixtures, SQL seed data), archives (`.zip`, `.tar.gz`).

#### Ignored

Truly invisible — not mentioned anywhere in generated documentation, not included in package
summaries. Pruned during directory walk where possible.

Examples: generated directories (`node_modules/`, `build/`, `dist/`, `target/`, `__pycache__/`,
`.git/`, `.venv/`), lockfiles (`package-lock.json`, `Cargo.lock`, `poetry.lock`, `yarn.lock`),
tool boilerplate config (`.prettierrc`, `.eslintrc`, `.editorconfig`, `.gitignore`,
`.gitattributes`), previous docai output (`.docai/`).

#### Unknown

Files that couldn't be classified by the detection stack. Warned about, skipped from
processing. Available for user override via `!` patterns in `.docaiignore`, which triggers
LLM identification validated against the known type registry.

### Extraction method map

A plugin registry mapping file types to extraction strategies. The Structure Extractor looks
up the file's type in this map to determine how to extract structure. The map is the single
source of truth for extraction strategy.

**Tier 1 — Full tree-sitter extraction.** For first-class programming languages. Tree-sitter
grammar + entity mapping table + import pattern table + import resolution heuristics +
visibility rules. Produces full entity directory and resolved dependencies. Error handling:
ERROR nodes trigger LLM verification of entity directory (ADR-003).

v1 languages: Python, JavaScript/TypeScript, Rust, Go, Java, C/C++. All grammars bundled
with the package.

**Tier 2 — Heuristic import check.** For config-like and markup files. A small list of regex
patterns per file type checking for import-like constructs only. If no patterns match →
return zero entities, zero imports immediately (free, instant). If a pattern matches →
escalate to LLM to resolve the import against the file manifest. Never does entity
extraction.

v1 heuristic plugins:

| File type | Import patterns | Behavior when no match |
|-----------|----------------|------------------------|
| SCSS/SASS/LESS | `@import`, `@use`, `@forward` | Return empty |
| HTML | `{% import`, `{% from`, `{% include` (template engines) | Return empty |
| CSS | `@import` | Return empty |
| Makefile/Justfile | `include` | Return empty |
| GraphQL | `#import`, cross-file `extend` | Return empty |
| Dockerfile | *(no patterns)* | Always return empty |
| YAML/TOML/JSON config | *(no patterns)* | Always return empty |
| SQL | *(no patterns)* | Always return empty |

**Tier 3 — LLM fallback.** For programming language files without a Tier 1 tree-sitter
config. Full entity extraction + import resolution via LLM (receives file content, file
manifest, and entity taxonomy). Only applies to source files — config-like files without
a Tier 2 plugin simply return empty results; they do not fall through to Tier 3.

**Lookup logic:** Discovery determines file type → Structure Extractor checks extraction
method map:
- Tier 1 entry found → full tree-sitter extraction
- Tier 2 entry found → heuristic import check
- No entry found AND file is a recognized programming language → Tier 3 LLM fallback
- No entry found AND file is not a recognized programming language → return empty
  FileAnalysis (config file with no entities, no imports)

**Plugin architecture from v1** — extraction method configs (both Tier 1 and Tier 2) are
loadable from external packages at runtime. Community-contributed configs conform to the
extraction method schema. Adding support for a new language or file type is a data/config
task, not a code change.

### User control

**`.docaiignore`**: full `.gitignore` syntax with `!` negation. Applied in two phases —
directory pruning during walk, file-level overrides after detection. Built-in defaults are
treated as preceding user rules, so user rules always win.

**Unknown file override flow**: user force-includes via `!` pattern → LLM identifies
language → validated against known type registry → proceed or warn. If identification fails
or the file cannot be read, no FileAnalysis is produced — pipeline logs a warning and moves
on.

### Package rules

Two package types, evaluated bottom-up (leaf directories first):

**Normal package** — a directory contains 2+ documentable items as direct children.
Documentable items: processed files, child normal packages, child asset packages. These
count uniformly — 1 processed file + 1 child package = 2 items = package.

**Asset package** — a directory contains only asset files (plus ignored/documentation/unknown
— no processed files), no child packages, and meets a configurable count threshold
(default: 5).

Bottom-up evaluation means package status propagates upward naturally. When two sibling
directories each become packages, their parent becomes a package too. The documentation
hierarchy grows organically with the project structure.

### Changes from original ADRs (ADR-005, ADR-007, ADR-008)

The original design had Discovery classify files as "source code" or "code-like config" and
this classification gated whether the file entered the Structure Extractor. Now Discovery
only determines file type and language — the Structure Extractor decides the extraction
strategy via the extraction method map.

Key changes:
- **Source code and code-like config merged into "processed"** — all enter the Structure
  Extractor. File type (source file, source-like config, config file) is determined by the
  FileAnalysis after extraction, not by Discovery before.
- **New "asset" classification** — binary and resource files are no longer lumped with
  "ignored." Their filenames and types are included in package summaries via the directory
  registry.
- **New "documentation" classification** — existing project docs get Pass 1 purpose sentences
  and appear in package summaries, but their content is never consumed as LLM context.
- **Extraction method map replaces the source/config pipeline split** — the three-tier
  plugin system determines extraction strategy per file type.
- **ProcessingPlan simplified** — two work item types (`file`, `package_summary`). The
  Documentation Generator checks the FileAnalysis to determine documentation depth.
- **Two package types** — normal packages (2+ documentable items) and asset packages
  (assets only, configurable threshold). Replaces the simpler "2+ documented files" rule.

---

## System Architecture

### Architectural style

**Pipeline / transform chain** with a **disk-backed project state store** as a cross-cutting
persistence layer. Data flows through well-defined stages, with each stage reading from and
writing to the state store. This combines the natural fit of a pipeline for a CLI processing
tool with crash recovery and incremental regeneration requirements.

### Implementation

**Python**, packaged as a CLI tool via **uv**. CLI built with **Typer** (type-hint-driven,
Rich-integrated). Progress reporting via **rich** library. LLM integration via **LiteLLM**
— a unified routing layer supporting multiple providers (Gemini, Claude, GPT-4o, etc.) with
built-in cost tracking, token counting, and success/failure callbacks. Primary provider:
Google Gemini. All data structures use **Pydantic v2** models for validation, serialization,
and LLM structured output schema generation.

### Component overview

Seven major components plus shared infrastructure:

```
User invokes CLI
       │
       ▼
   CLI (ADR-012, ADR-024)
       │  parses args, loads config, sets up logging/display
       │
       ▼
   Workflow (ADR-024)
       │  orchestrates pipeline, inter-step validation
       │
       ├─ Initializes LLM Service (validates API key)
       ├─ Initializes or loads Project State (ADR-011)
       │
       ▼
   File Discovery (ADR-007)
       │  file manifest + directory registry
       ▼
   Structure Extractor (ADR-008, ADR-014)  ← extraction method map determines strategy
       │  FileAnalysis per file → saved to Project State
       │  (entities with categories and kinds; file type derived)
       ▼
   Graph Builder (ADR-009)
       │  ProcessingPlan (ordered work item buckets) → saved to Project State
       ▼
   Documentation Generator (ADR-010, ADR-014)
       │  Pass 1: orientation sweep → purposes saved to Project State
       │  Pass 2: detailed docs per bucket → docs saved to Project State
       │  (depth per entity driven by LLM complexity assessment)
       ▼
   Output written to documentation directory
```

### Path handling invariant

All paths stored in `.docai/` state files are **relative to the project root**. Absolute
paths are constructed only at I/O boundaries (`project_root / relative_path`). This ensures
the entire `.docai/` directory is portable across machines and directory locations.

---

## Component Details

### 1. File Discovery

Walks the project directory and produces the file manifest and directory registry consumed
by all downstream components.

**Detection stack** (ordered, first match wins):

1. **Directory pruning** — built-in exclusions (`.git/`, `node_modules/`, `__pycache__/`,
   `build/`, `dist/`, `target/`, `vendor/`, `.docai/`, etc.) and `.docaiignore` directory
   patterns prune entire subtrees during traversal
2. **Magic byte detection** — first 4-8 bytes checked against known binary signatures (ELF,
   PNG, JPEG, PDF, ZIP, etc.) → classify as asset
3. **Filename map** — exact match for extensionless files (Dockerfile, Makefile, Justfile,
   Jenkinsfile, Rakefile, etc.) → classify with language and category
4. **Shebang detection** — `#!/usr/bin/env python3` → python/source, etc.
5. **Extension map** — `.py` → python/processed, `.rs` → rust/processed,
   `.yml` → yaml/processed, `.md` → markdown/documentation, `.png` → image/asset, etc.
6. **`.docaiignore` file-level overrides** — exclusion patterns and `!` negation for
   force-includes. User intent overrides all automatic classification.
7. **No match** → classify as **unknown**, warn user, skip processing

**Five file classifications**: processed (enters Structure Extractor), documentation
(Pass 1 purpose + package summaries), asset (directory registry), ignored (invisible),
unknown (warned, skippable).

**Symlinks**: ignored by default, warning emitted. Force-included symlinks (`!` pattern in `.docaiignore`) are processed normally.

**Two outputs**:
- **File manifest**: `dict[str, ManifestEntry]` keyed by relative path. Per-file:
  classification, language, content hash, override. Content hash computed for: processed
  files not force-excluded, and force-included non-asset files. All other files have
  `content_hash = None`.
- **Directory registry**: `dict[str, DirectoryEntry]` keyed by relative directory path.
  Per-directory: direct child files (non-asset), child packages, asset summary. Each
  `DirectoryEntry` exposes a `content_hash()` method (SHA256 of stable JSON serialization)
  used by status reconciliation.

Both manifests are regenerated fresh on every run — they are not persisted to `.docai/`.

### 2. Structure Extractor

Analyzes individual files to produce entity directories and resolved dependencies.
Encapsulates all extraction strategy differences behind a uniform output contract.

**Design philosophy**: LLM as the capable default, tree-sitter as accelerator. The LLM
extraction path is the universal baseline — designed, tested, and maintained as first-class.
Tree-sitter language configs are optimizations layered on top for high-frequency languages.

**Internal organization**: extraction method map — a plugin registry mapping file types to
extraction strategies across three tiers (full tree-sitter, heuristic import check, LLM
fallback). Per-language knowledge for Tier 1 is expressed as configuration tables (entity
mapping, import patterns, resolution heuristics, visibility rules), not code.

**v1 tree-sitter languages** (Tier 1): Python, JavaScript/TypeScript, Rust, Go, Java, C/C++.
All grammars bundled with the package.

**Extraction paths:**

| File type | Extraction tier | Entity extraction | Import extraction | Cost |
|-----------|----------------|-------------------|-------------------|------|
| Source file with Tier 1 config, clean parse | Tier 1 | Full entity directory | Full import resolution | Free |
| Source file with Tier 1 config, ERROR nodes | Tier 1 + LLM verify | Full entity directory, LLM-verified | Full import resolution | 1 cheap LLM call |
| Source file without Tier 1 config | Tier 3 (LLM fallback) | Full entity directory | Full import resolution | 1 LLM call |
| Config-like file with Tier 2 plugin, import found | Tier 2 + LLM resolve | None (single Module entity) | LLM resolves imports | 1 cheap LLM call |
| Config-like file with Tier 2 plugin, no import | Tier 2 | None (single Module entity) | None | Free |
| Config-like file without plugin | No extraction | None (single Module entity) | None | Free |

**Import resolution**: Tier 1 extracts raw import strings from the AST then resolves against
file manifest using per-language heuristics. Tier 2 escalates to LLM when import patterns
are found. Tier 3 LLM returns resolved project file paths directly (receives file manifest
as context). All paths produce the same output — downstream components don't know which
extraction method was used.

**FileAnalysis output contract**:
```
FileAnalysis:
  file_path: str                # relative path, matches manifest key
  file_type: FileType           # source_file | source_like_config | config_file | other
  entities: list[Entity]        # populated only for source_file; empty for all others
  dependencies: list[str]       # resolved project file paths
```

**Entity extraction model** — a thin table of contents, five fields per entity:
```
Entity:
  category: EntityCategory      # callable | macro | type | value | implementation
  name: str                     # entity name only (not qualified)
  kind: str                     # freeform variant label (function, method, class, etc.)
  parent: str | None            # dotted scope path from module root (e.g. "OuterClass.Inner"),
                                #   or None if top-level. Fully qualified to avoid ambiguity
                                #   when multiple types share the same name in one file.
  signature: str | None         # full signature as it appears in source
```

The extraction model is intentionally minimal. All documentation richness (descriptions,
parameters, side effects, error behavior, complexity judgments) is produced by the
Documentation Generator when it has the full source code.

**LLM fallback extraction pipeline** (`extractor/llm_fallback.py`): two focused LLM calls:
1. **Type + deps call** — determines `FileType` and `dependencies`. Validator ensures all
   returned paths exist in the file manifest, and that `source_like_config` always has
   non-empty dependencies (source_like_config is defined by having imports).
2. **Entity call** — extracts entities. Only executed when `file_type == source_file`;
   skipped entirely for config_file, source_like_config, and other.

**Main entry point** (`extractor/extractor.py`):
1. Cache check via `get_analysis()` — hit → return immediately
2. Read file content — `PermissionError` → `ExtractionError(EXTRACTION_READ_FAILED)`
3. Dispatch: tree-sitter (not yet implemented) → heuristic (not yet implemented) → LLM fallback
4. `save_analysis()` → return result
5. `DocaiError` propagates unchanged; bare `Exception` wrapped as `EXTRACTION_UNEXPECTED_ERROR`

**Error codes** (`extractor/errors.py` — `ExtractionError(DocaiError)`):
- `EXTRACTION_READ_FAILED` — file content unreadable, message: `"Content not readable for file: {path}"`
- `EXTRACTION_LLM_FAILED` — LLM call failed, message: `"File Analysis failed for {path}"`
- `EXTRACTION_UNEXPECTED_ERROR` — unexpected exception, message: `"File Analysis failed for {path}: {e}"`

**LLM output format**: Pydantic structured output via `LLMService.generate(structured_output=...)`.
Validated with retry feedback. Up to 3 validation retries before marking as failed.

### 3. Graph Builder

Builds the project-wide dependency graph and produces the ProcessingPlan for documentation
generation.

**Input**: resolved dependency lists from all FileAnalysis results, directory registry with
package rules.

**Output**: ProcessingPlan with ordered buckets for concurrent execution.

**ProcessingPlan model**:
```
ProcessingPlan:
  buckets: list[list[WorkItem]]

WorkItem:
  type: WorkItemType            # file | package_summary
  path: str                     # relative file path or directory path
```

**Bucket assignment algorithm**:
1. Build file-level dependency graph from FileAnalysis
2. Detect strongly connected components (cycles) via Tarjan's algorithm
3. Break cycles by placing the file with fewest cross-cycle dependencies in an earlier bucket
4. Compute bucket assignment via level-based topological sort:
   - Bucket 0: leaf files (no dependencies) + isolated files
   - Bucket N: files whose dependencies are all in buckets 0 through N-1
5. Schedule `package_summary` work items per package rules. Each package summary is placed
   in the bucket after the last of its constituent files and child package summaries
6. Package summaries follow bottom-up directory order (children before parents)

**Cycle handling**: no special case needed. Context assembly follows one universal rule —
use generated docs if available, fall back to raw source + entity directory if not.

**Concurrency model**: asyncio-based. One bucket at a time, all items in a bucket processed
concurrently up to `max_concurrent_calls` limit.

**No persisted dependency graph**: the graph is built transiently during bucket computation.
Forward dependency lists on FileAnalysis are the source of truth. Incremental invalidation
uses an invalidated set propagated through bucket order (see Project State).

### 4. Documentation Generator

Orchestrates LLM calls to produce documentation. The most consequential component for output
quality.

**Pass 1 — Orientation sweep**: cheap LLM call(s) producing one-sentence purpose for every
file and directory. Input is the project tree, file names, and entity directories (entity
names and categories only — no file content, no signatures, no source code). Provides
big-picture awareness at ~1-2% of total pipeline cost. Batched by directory when project
exceeds file + directory count threshold (~50-80 items).

**Pass 1 output**: `dict[str, str]` — one combined dict mapping relative paths (files and
directories) to purpose sentences.

**Pass 2 — Detailed documentation**: processes buckets from ProcessingPlan in order.

**Context assembly per file** (applies to all processed files — source, source-like config,
and config):
1. Project description (user-provided)
2. Directory context (purpose sentences for all parent directories, from Pass 1)
3. File purpose (from Pass 1)
4. Full source code of the file
5. For each direct project dependency:
   a. Module purpose sentence (from Pass 1)
   b. Complete entity name list (names only — compact overview)
   c. Full documentation for referenced entities only (matched via lowercase entity name
      appearing in lowercased file source)
   d. If no generated docs exist: raw source code + entity directory as fallback

**No context truncation.** Full context assembled as designed. Warning emitted if context
exceeds configurable token threshold. LLM API error on context overflow is logged, file
marked as failed.

**Unprocessed dependency fallback chain**:
1. Generated docs exist → use them
2. FileAnalysis exists but no docs → entity directory + raw source
3. File exists but no FileAnalysis → raw source only
4. File doesn't exist (external) → no context, LLM uses training knowledge

**Documentation depth per file** — determined by FileAnalysis content:
- **Files with entities** (source files): per-file LLM call producing module overview + all
  entity documentation. The LLM determines depth from the actual source code and assigns a
  complexity rating per entity (trivial/standard/complex). Entities rated `complex` get
  individual follow-up calls with focused prompts for richer documentation.
- **Files without entities** (source-like config, config files): single LLM call producing
  module-level summary only.

**File documentation output**:
```
FileDocumentation:
  module_overview: str
  entities: dict[str, EntityDocumentation] | None   # None for config files
```

**Completeness verification** (source files only): the response schema requires per-entity
documentation keyed by entity name. Validator checks all entities from FileAnalysis are
accounted for — either as standalone entries or in a Type's `protocol_methods` or
`folded_accessors` list. Missing entities trigger correction call. Up to 3 validation retries.

**Hybrid mode**: after the per-file documentation call, entities flagged `complexity=complex`
get individual follow-up calls. The follow-up response replaces the initial documentation
for that entity. This is driven by LLM complexity assessment, not entity count thresholds.

**Output assembly** — entirely programmatic:
- YAML frontmatter: assembled from FileAnalysis + manifest data (never LLM-generated)
- Module overview: from LLM JSON response
- Per-entity sections: from LLM JSON response (source files only)
- Markdown formatting: from templates

**Package summary documentation**: LLM call with all constituent file overviews, child
package summaries, and asset listings from the directory registry as context. Output is a
single `overview` string.

**LLM client**: `LLMService.generate(prompt, *, system_prompt, structured_output, validator)`
over **LiteLLM**. LiteLLM handles provider routing, structured output translation (JSON
schema → provider-native format), token counting, and cost tracking. The service adds
multi-model failover, validation retry loops, and structured logging on top.

**Multi-model profile**: `LLMProfile` holds an ordered `list[ModelConfig]`. On failure,
the service moves to the next model in the list. Primary model: Google Gemini
(`gemini-2.0-flash`). Switching models or providers is a config string change.

**Retry strategy**: per-model validation retries (default 3, with error feedback appended
to conversation) for parse or validation failures. On connection error the service moves
directly to the next model. All retries exhausted → `LLMError(code="LLM_ALL_MODELS_FAILED")`.

### 5. Project State

Disk-backed persistence layer for all intermediate and final artifacts. Owns the `.docai/`
directory.

**Directory structure**:
```
.docai/
  version                    # state format version (plain text)
  lock                       # PID lockfile (gitignored)
  purposes.json              # dict[str, str] — Pass 1 purpose sentences
  graph.json                 # ProcessingPlan — ordered work item buckets
  status.json                # dict[str, FileStatus] — generation status per file and package
  logs/                      # detailed per-call metrics for benchmarking
  analyses/                  # FileAnalysis per processed file (mirrors source tree)
  docs/                      # generated documentation (mirrors source tree)
```

File manifest and directory registry are **not persisted** — they are regenerated fresh on
every run by the Discovery component.

**Atomic writes**: all disk writes use write-to-temp-then-rename. Leftover `.tmp` files
cleaned up on startup.

**Status reconciliation** (runs every time, after Discovery): status.json is the ground
truth for incremental processing. After Discovery produces fresh manifests, the state
module reconciles against the stored status:

Tracked entries: all files where `ManifestEntry.content_hash is not None` (processed files
not force-excluded, and force-included non-assets), plus all packages in the directory
registry.

Reconciliation rules:
- Entry in manifests, not in status → add as `pending`
- Entry in manifests, status `complete`, same hash → keep `complete` (skip generation)
- Entry in manifests, status `complete`, different hash → mark `deprecated`
- Entry in manifests, status `deprecated` → keep `deprecated`
- Entry in manifests, status `failed` → reset to `pending`
- Entry in manifests, status `remove` → mark `deprecated` (file reappeared)
- Entry in status, not in manifests → mark `remove`

**Incremental invalidation**: entries marked `deprecated` (and transitively, anything whose
dependency chain includes a `deprecated` entry) are regenerated. Propagation uses the
forward dependency lists on FileAnalysis and the ordered ProcessingPlan buckets — no reverse
dependency index needed.

**Status tracking**: `dict[str, FileStatus]` in `.docai/status.json`. Covers both files
and package directories.
```
FileStatus:
  status: GenerationStatus      # pending | complete | deprecated | failed | remove
  content_hash: str             # hash at time of generation (or directory content hash)
  error: str | None             # error message when failed
```

**State versioning**: version number in `.docai/version`. On mismatch, warn user and
regenerate.

**Concurrent access**: lockfile (`.docai/lock`) with PID prevents simultaneous runs.

**Git-committable**: `.docai/` is designed to be committed to version control. Team members
clone, run `docai`, hashes match, instant completion. Only `.docai/lock` and `*.tmp` are
gitignored.

**Analyses cache API** (`state/analyses.py`):
- `get_analysis(file_path: str) -> FileAnalysis | None` — reads `.docai/analyses/<file_path>.json`; returns `None` on miss; raises `StateError(STATE_PERMISSION_DENIED)` or `StateError(STATE_CORRUPT)` on errors.
- `save_analysis(analysis: FileAnalysis) -> None` — atomic write to `.docai/analyses/<analysis.file_path>.json`; creates intermediate directories; raises `StateError(STATE_PERMISSION_DENIED)` on `PermissionError`.
- `purge_analyses() -> None` — call after `reconcile_status()`; deletes analysis files whose status is `deprecated`, `remove`, or absent from `status.json`; removes empty parent directories bottom-up; wraps all errors as `StateError(STATE_PURGE_FAILED)`.

### 6. LLM Connector

Encapsulates all LLM interaction: client abstraction, agent loop, tool functions, structured
output, retries, and validation.

**LLM service construction validates credentials.** If the API key is invalid, the service
is never created — this surfaces as a `ConfigError` during workflow initialization, before
the pipeline starts (ADR-023).

**Agent tool functions** use a two-layer pattern (ADR-022): underlying implementations
(fuzzy search, file reading, documentation lookup) live in `core/`, thin wrappers adapting
them to the agent's calling convention (parameter schemas, structured return types,
LLM-friendly error formatting) live in `llm/`.

**Internal error handling**: connection errors, rate limits, and validation failures are
retried internally. Only when all retries are exhausted does an `LLMError` surface to the
calling component, which wraps it as its own `ComponentError` subclass (ADR-023).

### 7. CLI / Orchestrator

User interface layer. Handles argument parsing, user interaction, configuration loading,
and logging/display setup.

**Commands**:

| Command | Description |
|---------|-------------|
| `docai` | Init (if needed) + generate |
| `docai init` | Create `docai.toml`, prompt for description, preview discovery |
| `docai generate` | Run pipeline (incremental or full) |
| `docai generate --force` | Regenerate everything, ignore cache |
| `docai generate <path>` | Document specific file/directory only |
| `docai status` | Show documentation state |
| `docai list` | Show file manifest with classifications and file types |
| `docai clean` | Remove `.docai/` state directory |

**Configuration**: `docai.toml` in project root (TOML format, committed to git). CLI flags
override config. Config overrides defaults.

```toml
[project]
description = "..."

[generation]
max_concurrent_calls = 5
context_warning_tokens = 80000
asset_package_threshold = 5

[llm]
provider = "gemini"
model = "gemini/gemini-2.0-flash"
# api_key = "..."           # prefer environment variable
connection_retries = 3
validation_retries = 3
input_token_cost = 0.00015  # optional, for cost reporting
output_token_cost = 0.0006  # optional, for cost reporting

[output]
directory = ".docai/docs"
```

**API key**: environment variable (primary) → config file (secondary, with security warning)
→ prompt user.

**Project description**: CLI flag → config file → auto-detect from `pyproject.toml` /
`package.json` / `Cargo.toml` → interactive prompt during init.

**Progress reporting**: `rich` progress bar showing LLM calls remaining. Total updates
dynamically when per-entity follow-ups are determined. Default shows stage-level progress
with file type counts (e.g., "98 source files, 12 source-like configs, 22 config files"),
`-v` adds per-file detail, `-q` shows warnings/errors only. Warnings always shown.

**Cost reporting**: confirmation prompt shows LLM call range estimate (minimum to ~120%).
Post-run summary shows actual calls, tokens, and estimated cost (if pricing configured).
Detailed per-call log in `.docai/logs/` for benchmarking.

**Confirmation prompt**: always on first run. On incremental runs, only when 20+ files
affected. Skippable with `--yes`.

**Output directory**: default `.docai/docs/`, configurable. Write strategy: overwrite only,
never wipe. Orphan cleanup removes docs for deleted source files.

### 8. Workflow

Pipeline orchestration layer, separate from the CLI (ADR-024). Defines the sequencing of
pipeline stages, inter-step validation, and component coordination.

Each CLI command maps to a workflow. The workflow contains the logic for "create LLM
service → run discovery → run extraction → build graph → generate docs" including
validation between steps (e.g., verifying the LLM service was created successfully before
entering the pipeline, checking that discovery found processable files).

The workflow drives progress updates through a lightweight callback for the few places
where live progress bars are needed (extraction, generation). All other status communication
flows through standard logging.

---

## Project Structure

### Package layout (ADR-022)

Nine top-level packages under `src/docai/`:

```
src/docai/
  cli/                 # argparse, user interaction, config loading, log/display setup
  core/                # file I/O, hashing, cache, search/fuzzy match, shared types/enums
  discovery/           # file walk, detection stack, manifest + directory registry
  extractor/           # structure extraction (tiers 1-3), plugin system, language configs
  graph/               # dependency graph, bucket computation, ProcessingPlan
  generator/           # doc generation (Pass 1, Pass 2, context assembly, output)
  state/               # .docai/ management, persistence, crash recovery, locking
  llm/                 # client wrapper, agent loop, structured output, retries, tool wrappers
  workflow/            # pipeline orchestration, inter-step validation, workflow definitions
```

### Model placement (ADR-022)

Pydantic models live with their producing component:
- `ManifestEntry`, `DirectoryEntry` → `discovery/`
- `FileAnalysis`, `Entity` → `extractor/`
- `ProcessingPlan`, `WorkItem` → `graph/`
- `FileDocumentation`, entity documentation union → `generator/`
- `FileStatus` → `state/`
- `DocaiConfig` → `cli/`

Cross-cutting types (`FileClassification`, `EntityCategory`, `FileType`, and other shared
enums/primitives) live in `core/`.

Model imports follow the pipeline's directional flow — downstream components import from
upstream producers. No circular dependencies.

### Shared infrastructure — `core/` (ADR-022)

Cross-cutting functionality used by multiple packages:
- **File I/O**: reading files, path utilities (relative-path invariant)
- **Hashing**: content hash computation
- **Cache**: shared caching infrastructure
- **Search / fuzzy matching**: used by extractor and generator at minimum
- **Shared enums and types**: cross-cutting primitives

The bar for inclusion: used by 3+ packages and doesn't logically belong to any single
component.

### LLM agent tool functions (ADR-022)

Two-layer split: `core/` owns the implementations (pure functions any component can import),
`llm/` owns thin tool wrappers adapting those functions to the agent's calling convention.
One implementation, two interfaces.

### Test organization (ADR-025)

Separate `tests/` tree mirroring the package structure:

```
tests/
  test_core/
  test_discovery/
  test_extractor/
  test_graph/
  test_generator/
  test_state/
  test_workflow/
  fixtures/              # scenario-based mini projects
```

Fixtures organized by scenario (not language): `small_python_project/`, `circular_deps/`,
`tier2_imports/`, `mixed_languages/`, `error_cases/`, `tree_sitter_errors/`. Each is a
self-contained mini project directory.

LLM calls mocked at the wrapper interface in unit/integration tests. Output quality
validation is a separate benchmarking activity using `.docai/logs/`.

---

## Error Handling (ADR-023)

### Three error levels

**Component-internal** — raised and caught within the same component. Part of internal
recovery logic (retries, fallback strategies). The orchestrator never sees these.

**Recoverable (`ComponentError`)** — component exhausted internal recovery, cannot process
this unit of work. Orchestrator logs, marks file as failed, continues pipeline.

**Fatal (`PipelineError`)** — pipeline cannot continue. Orchestrator reports to user and
exits.

### Exception hierarchy

Flat — all errors inherit directly from `DocaiError`. The workflow decides whether an error
is fatal (re-raise as `PipelineError`, exit 2) or recoverable (log, mark file failed,
continue, exit 1).

```
DocaiError (base)          # src/docai/errors.py
├── PipelineError          # workflow/  — workflow decided this is a dealbreaker
├── ConfigError            # cli/       — bad/missing config, before pipeline starts
├── StateError             # state/     — .docai/ corrupt, locked, version mismatch
├── LLMError               # llm/       — LLM interaction failure
├── CoreError              # core/      — shared utility failure
├── DiscoveryError         # discovery/
├── ExtractionError        # extractor/
├── GraphError             # graph/
└── GenerationError        # generator/
```

All errors carry two fields: `code` and `message`. `__cause__` follows standard Python
exception chaining.

- `message` — human-readable description of what went wrong
- `code` — machine-readable identifier following the convention `COMPONENT_WHAT_HAPPENED`
  (uppercase with underscores). Examples: `EXTRACTION_PARSE_FAILED`, `CONFIG_MISSING_API_KEY`,
  `LLM_RATE_LIMIT`, `STATE_LOCKED`, `PIPELINE_NO_FILES`. Each component defines its own
  codes alongside its error class.

### CLI exit codes

| Code | Meaning |
|------|---------|
| **0** | Success — all files documented |
| **1** | Partial success — pipeline completed but some files failed |
| **2** | Fatal error — pipeline could not complete |

---

## Configuration and Logging (ADR-024)

### Configuration loading

**Field-level merging** across four precedence layers: defaults (Pydantic field defaults) <
config file (`docai.toml`) < environment variables < CLI arguments. Each layer overrides
individual fields, not entire sections.

Validation at load time — structural (Pydantic) and semantic (`max_concurrent_calls > 0`,
etc.). Invalid config raises `ConfigError` before the pipeline starts. LLM service
construction (API key validation) happens during workflow initialization.

**Selective CLI flag exposure**: only frequently changed settings (model, output directory,
`--force`, `--yes`, `-v`, `-q`, path argument) are CLI flags. Rarely changed settings are
config-file only.

### Logging

**Standard library `logging`** is the primary output mechanism. Components use module-level
loggers (`logging.getLogger(__name__)`) and never import `rich` or manage their own output.

Verbosity: `-v` → DEBUG, default → INFO, `-q` → WARNING. File logging to `.docai/logs/`
captures all levels regardless of console verbosity.

### Display

**Shared `rich.console.Console`** created once in `cli/`, used by both `RichHandler` (for
log output) and `rich.progress` (for progress bars). Prevents output conflicts. All output
to stderr.

Progress bars are narrowly scoped to concurrent processing loops (extraction, generation).
Everything else flows through standard logging.

---

## Data Models

All data structures use **Pydantic v2** models. Pydantic was chosen for three reasons:
LLM structured output (`.model_json_schema()` generates schemas for GenAI API responses),
disk persistence (`.model_dump_json()` / `.model_validate_json()` for the `.docai/` state
directory), and runtime validation of LLM responses and loaded state files.

### File Manifest (ADR-015)

```
ManifestEntry:
  classification: FileClassification    # processed | documentation | asset | ignored | unknown
  language: str | None                  # None for assets, docs, ignored, unknown
  content_hash: str | None              # SHA-256, only for files entering the extractor
  override: FileOverride | None         # include | exclude | None
```

Classification records what Discovery's detection stack determined — permanent identity.
Override records user intent from `.docaiignore` — changes pipeline behavior, not identity.

### Directory Registry (ADR-018)

```
DirectoryEntry:
  files: list[str]                      # direct child file paths
  subdirectories: list[str]             # direct child directory paths
  asset_summary: AssetSummary | None

AssetSummary:
  count: int
  types: dict[str, int]                 # extension -> count
```

### FileAnalysis (ADR-016)

```
FileAnalysis:
  file_path: str
  file_type: FileType                   # source_file | source_like_config | config_file | other
  entities: list[Entity]
  dependencies: list[str]
```

`other` — force-included unknown files where the LLM cannot classify the file as
source_file, source_like_config, or config_file. Gets a plain description only.

### Entity — Extraction Model (ADR-017)

```
Entity:
  category: EntityCategory              # callable | macro | type | value | implementation
  name: str
  kind: str
  parent: str | None
  signature: str | None
```

### Entity — Documentation Model (ADR-020)

Discriminated union on category. Per-category fields listed in "What is documented about
each entity" above. Shared fields: description (always), notes (catch-all list), complexity
(trivial | standard | complex).

### ProcessingPlan (ADR-019)

```
ProcessingPlan:
  buckets: list[list[WorkItem]]

WorkItem:
  type: WorkItemType                    # file | package_summary
  path: str
```

### Pass 1 Purposes (ADR-020)

```
purposes: dict[str, str]               # relative path -> purpose sentence
```

### File Documentation (ADR-020)

```
FileDocumentation:
  module_overview: str
  entities: dict[str, EntityDocumentation] | None
```

### Status Tracking (ADR-021)

```
FileStatus:
  status: GenerationStatus              # pending | complete | deprecated | failed | remove
  content_hash: str
  error: str | None

GenerationStatus:
  pending     — in plan, not yet started (or reset from failed)
  complete    — generated successfully, hash matches
  deprecated  — hash changed since last generation, or file reappeared after removal
  failed      — generation failed; error field populated; reset to pending on next run
  remove      — no longer present in manifests
```

Applies to both files and package directories. See reconciliation rules in Project State.

### Configuration (ADR-021)

```
DocaiConfig:
  project: ProjectConfig                # description
  generation: GenerationConfig          # max_concurrent_calls, context_warning_tokens,
                                        #   asset_package_threshold
  llm: LLMConfig                        # provider, model, api_key, retries, costs
  output: OutputConfig                  # directory
```

---

## Language Support

Universal by default via LLM. Six languages optimized with tree-sitter configs in v1:
Python, JavaScript/TypeScript, Rust, Go, Java, C/C++.

Language configs use a plugin architecture — loadable from external packages at runtime.
Community-contributed configs conform to the extraction method schema. Tier 1 configs
include: entity mapping table (AST nodes → categories + kinds), import pattern table,
resolution heuristics, visibility rules. Tier 2 configs include: import pattern list with
escalation rules.

Known languages: omit inapplicable entity categories and documentation aspects (e.g., no
Implementation category for Python, no Macro category for Python). Unknown languages:
include all categories and aspects, let the LLM determine relevance.

---

## Key Constraints

- Solo developer project
- CLI tool, runs locally, Python + uv
- No source code modification in v1
- Must work across programming languages
- LLM-powered (Google GenAI SDK with thin wrapper for provider switching)
- All data structures use Pydantic v2 models
- Documentation is for code comprehension, not bug fixing
- All stored paths relative to project root (portability invariant)
- `.docai/` is git-committable and team-shareable

---

## Source ADRs

### Domain Analysis (phase 1)
- **ADR-001**: Domain model and problem scope
- **ADR-002**: Analysis pipeline, context management, output format, regeneration
- **ADR-003**: Parse error resilience and entity directory verification
- **ADR-004**: Entity taxonomy and documentation standards
- **ADR-005**: File type handling and documentation scope

### System Architecture (phase 2)
- **ADR-006**: System architecture and component decomposition
- **ADR-007**: File Discovery component design
- **ADR-008**: Structure Extractor component design
- **ADR-009**: Graph Builder component design
- **ADR-010**: Documentation Generator component design
- **ADR-011**: Project State component design
- **ADR-012**: CLI / Orchestrator component design
- **ADR-013**: Resolution of open questions from system architecture ADRs

### Data Modeling (phase 3)
- **ADR-014**: Revised file classification model and refined entity taxonomy — five file
  categories, three-tier extraction method map, six entity categories with kinds
- **ADR-015**: File Manifest data model — Pydantic v2 as modeling library, ManifestEntry
  fields, classification/override separation, language as string
- **ADR-016**: FileAnalysis data model — four-field model (file_path, file_type, entities,
  dependencies), diagnostic fields dropped, no manifest write-back
- **ADR-017**: Entity data model — single flat Entity with five fields (category, name,
  kind, parent, signature), extraction depth rule (top-level + type members), LLM-driven
  depth scaling, accessor handling deferred to documentation generation
- **ADR-018**: Directory registry and package rules — DirectoryEntry model, two package
  types (normal: 2+ documentable items, asset: assets only with threshold), bottom-up
  evaluation
- **ADR-019**: ProcessingPlan — ordered buckets of WorkItems, invalidated set propagation
  for incremental runs, no persisted dependency graph
- **ADR-020**: Documentation output model — Pass 1 purposes, per-category discriminated
  union (Callable, Macro, Type, Value, Implementation), complexity enum for hybrid mode,
  completeness verification via protocol_methods and folded_accessors
- **ADR-021**: Status tracking and configuration — FileStatus model, GenerationStatus enum
  (pending/complete/deprecated/failed/remove), unified status.json for files and packages,
  DocaiConfig model for docai.toml

### Project Structure (phase 4)
- **ADR-022**: Package structure and module boundaries — nine packages (cli, core, discovery,
  extractor, graph, generator, state, llm, workflow), models with producers, `core/` for
  shared infrastructure, two-layer agent tool pattern
- **ADR-023**: Error handling strategy — three error levels (internal, recoverable, fatal),
  per-component exception types, `LLMError` internal to `llm/` with wrapping pattern,
  upfront API key validation via service construction, CLI exit codes (0/1/2)
- **ADR-024**: Configuration, logging, and display — field-level config merging, selective
  CLI flag exposure, standard library logging as primary output, shared Rich console for
  progress bars, stderr for all output, `workflow/` package for pipeline orchestration
- **ADR-025**: Testing strategy — separate `tests/` tree mirroring packages, scenario-based
  fixtures, mock LLM at wrapper interface, output quality as benchmarking not CI
