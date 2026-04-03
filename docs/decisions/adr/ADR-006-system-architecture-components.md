# ADR-006: System Architecture and Component Decomposition

## Status
Accepted

## Context
ADRs 001-005 established the domain model, pipeline design, error resilience strategy, entity
taxonomy, and file type handling for docai. With the domain analysis complete, we need to
translate these decisions into a concrete system architecture: what the major components are,
what each is responsible for, how data flows between them, and where the boundaries fall.

### Architectural drivers

- **Primary execution path**: A three-pass pipeline (static analysis → orientation sweep →
  bottom-up documentation generation) as defined in ADR-002.
- **Deployment model**: CLI tool, runs locally, single process. Python with uv for packaging.
- **Key quality attributes**: cost efficiency (minimize LLM calls via caching and incremental
  regeneration), correctness (entity completeness verification), universality (any language
  via tree-sitter + LLM fallback).
- **Stateful operation**: The pipeline must persist intermediate artifacts to disk for crash
  recovery, incremental regeneration, and memory efficiency. LLM calls are expensive in both
  time and money — work already done must never be lost unnecessarily.

### Key design tension: import resolution

The two structure extraction paths (tree-sitter and LLM fallback) handle import resolution
differently:

- **Tree-sitter** extracts raw import strings from the AST (e.g., `from docai.parser import X`).
  These must be resolved to actual project files using the file manifest and language-specific
  heuristics.
- **LLM fallback** receives the file manifest as context and can return resolved project file
  paths directly, since it understands the project structure.

This asymmetry must be encapsulated — downstream components should receive uniformly resolved
dependencies regardless of which extraction path produced them.

## Options Considered

### Component granularity

#### Option A: Monolithic pipeline (one module orchestrates everything)
- **Pros**: Simple, no inter-component interface design needed
- **Cons**: Untestable, unmaintainable, all concerns tangled together

#### Option B: Fine-grained microcomponents (10+ components)
- **Pros**: Maximum separation of concerns
- **Cons**: Over-engineered for a solo developer project. Interface overhead dominates.
  Premature abstraction.

#### Option C: Six major components aligned to pipeline stages and cross-cutting concerns
- **Pros**: Each component has a clear single responsibility, natural data flow boundaries,
  testable in isolation. Manageable for a solo developer.
- **Cons**: Some components (Structure Extractor, Documentation Generator) have significant
  internal complexity that will need sub-module organization

### Import resolution ownership

#### Option A: Graph Builder resolves imports
- **Pros**: Graph Builder already has the file manifest, resolution is a cross-file concern
- **Cons**: Leaks the difference between tree-sitter and LLM extraction paths into the Graph
  Builder. The Graph Builder would need to know which extraction method was used per file to
  decide whether imports need resolution.

#### Option B: Structure Extractor resolves imports
- **Pros**: Encapsulates the extraction path asymmetry. Tree-sitter path extracts raw imports
  then resolves them; LLM path returns resolved imports directly. Either way, the output
  contract is resolved file paths. The Graph Builder receives uniform input.
- **Cons**: Structure Extractor needs the file manifest as input, coupling it to Discovery
  output.

### State persistence model

#### Option A: Single `.docai` metadata file
- **Pros**: Simple, one file to manage
- **Cons**: Cannot update one file's data without rewriting the whole thing. Poor for crash
  recovery — a crash mid-write corrupts everything. Grows unwieldy for large projects.

#### Option B: `.docai/` directory with structured files
- **Pros**: Atomic updates per source file. Crash during one file's processing doesn't
  corrupt others. Natural mapping: one state file per source file, plus project-level files
  for the dependency graph and manifest. Scales to large projects.
- **Cons**: More filesystem complexity, directory management logic needed.

## Decision

### Architectural style

**Pipeline / transform chain** with a **disk-backed project state store** as a cross-cutting
persistence layer. Data flows through well-defined stages, with each stage reading from and
writing to the state store. This combines the natural fit of a pipeline for a CLI processing
tool with the crash recovery and incremental regeneration requirements.

### Implementation language

**Python**, packaged as a CLI tool via **uv**. Rationale:
- Mature tree-sitter bindings (`py-tree-sitter`)
- Strong LLM SDK ecosystem (Anthropic SDK, litellm for provider flexibility)
- Solo developer familiarity and productivity
- uv provides clean CLI packaging and dependency management

### Component decomposition

Six major components:

#### 1. File Discovery

**Responsibility**: Walk the project directory, apply `.docaiignore` rules and built-in
exclusion patterns, classify every file into one of three categories (source code, code-like
config, ignored) as defined in ADR-005.

**Input**: Project root path, `.docaiignore` file (if present).

**Output**: File manifest — an ordered list of files with their classifications, relative
paths from project root, and detected language (via file extension and/or tree-sitter grammar
availability).

**Knows about**: File system, ignore patterns, file classification rules.
**Ignorant of**: File contents, parsing, LLMs, documentation.

#### 2. Structure Extractor

**Responsibility**: Analyze a single source file to extract its entity directory and resolved
dependencies. Encapsulates the three extraction paths from ADR-003:
- Tree-sitter parse with no errors → extract entities + raw imports, resolve imports against
  file manifest
- Tree-sitter parse with ERROR nodes → extract entities + raw imports, LLM verification of
  entity directory, resolve imports against file manifest
- No tree-sitter grammar → full LLM structural analysis, which returns entities and resolved
  dependencies directly (LLM receives file manifest as context)

Import resolution for the tree-sitter paths uses the file manifest and language-specific
heuristics to map raw import strings to project files. Imports that don't resolve to any
project file are classified as external (standard library or third-party) and excluded from
the dependency list.

**Input**: Single source file, file manifest (from Discovery).

**Output**: FileAnalysis per file:
- Entity directory: list of entities with categories (per ADR-004 taxonomy), names, signatures,
  line ranges
- Dependencies: list of resolved project file paths this file imports from
- Parse errors detected: boolean
- Extraction method used: `tree-sitter` | `llm-verified` | `llm-fallback`

**Knows about**: Tree-sitter grammars, LLM structural analysis prompts, language-specific
import resolution heuristics, entity taxonomy (ADR-004).
**Ignorant of**: Dependency graph structure, documentation generation, pipeline ordering.

#### 3. Graph Builder

**Responsibility**: Consume all FileAnalysis results, build the project-wide dependency graph,
detect cycles, determine processing order for documentation generation.

**Input**: FileAnalysis results for all files (specifically the resolved dependency lists).

**Output**:
- Dependency graph (file-level, directed: edge from A to B means A imports from B)
- Topological processing order (leaves first), with cycle groups identified
- Cycle information: which files participate in which cycles

**Knows about**: Graph algorithms (topological sort, cycle detection).
**Ignorant of**: How dependencies were extracted, how files were parsed, what entities exist,
LLMs, documentation.

#### 4. Documentation Generator

**Responsibility**: Orchestrate LLM calls to produce documentation. Runs Pass 1 (orientation
sweep) and Pass 2 (detailed documentation) from ADR-002. Handles context assembly per file:
packing the right combination of project description, file purpose, source code, and
dependency documentation into each prompt. Manages the per-file vs. per-entity fallback for
large files (ADR-002). Runs tree-sitter completeness verification after generation and makes
targeted follow-up calls for missed entities.

**Input**: Project description (from user), FileAnalysis results, dependency graph with
processing order, previously generated documentation (for incremental runs and dependency
context).

**Output**: Documentation files — markdown with YAML frontmatter (per ADR-002 hybrid format)
for each documented file.

**Knows about**: LLM prompt construction, documentation format (ADR-002), entity documentation
standards (ADR-004), context assembly strategy, depth scaling.
**Ignorant of**: How files were discovered, how structure was extracted, graph algorithms.

#### 5. Project State

**Responsibility**: Persist and retrieve all intermediate and final artifacts. Owns the
`.docai/` directory. Provides the interface for crash recovery (which files have been
processed?), incremental regeneration (which files have changed?), and dependency-aware
cache invalidation (which files need re-documentation because a dependency changed?).

**Stores**:
- File manifest snapshot
- FileAnalysis per source file (entity directory, dependencies, extraction method)
- Dependency graph
- Content hash per source file
- Transitive dependency hashes (a file's docs are valid only if its own hash AND all
  dependency hashes match)
- Pass 1 file purposes
- Generation status per file (not started, in progress, complete, error)
- Parse error flags for priority regeneration
- Generated documentation files

**Knows about**: File system, hashing, serialization, cache invalidation logic.
**Ignorant of**: How any artifact was produced — only stores and retrieves.

#### 6. CLI / Orchestrator

**Responsibility**: Parse user commands, load or initialize project state, run the pipeline
stages in order, handle top-level control flow (full run vs. incremental update vs. force
regeneration). Owns progress reporting, error display, and user interaction (project
description prompt, confirmation of large runs).

**Input**: User command-line arguments, project state (if exists from prior run).

**Output**: Orchestrates all other components; final output is generated documentation
in the output directory.

**Knows about**: Pipeline stage ordering, user interaction, progress reporting.
**Ignorant of**: Internal details of any other component.

### Data flow

```
User invokes CLI
       │
       ▼
   CLI / Orchestrator
       │
       ├─ Initializes or loads Project State
       │
       ▼
   File Discovery
       │  file manifest
       ▼
   Structure Extractor  (per file, uses file manifest for import resolution)
       │  FileAnalysis per file → saved to Project State
       ▼
   Graph Builder
       │  dependency graph + processing order → saved to Project State
       ▼
   Documentation Generator
       │  Pass 1: orientation sweep → file purposes saved to Project State
       │  Pass 2: detailed docs in dependency order → docs saved to Project State
       ▼
   Output written to documentation directory
```

Each stage reads inputs from and writes outputs to Project State. If the pipeline crashes
at any point, the next run loads Project State and resumes from where it left off (skipping
files whose artifacts are already complete and whose source hashes haven't changed).

### Import resolution placement

**Import resolution lives inside the Structure Extractor** (Option B). The two extraction
paths handle resolution differently:

- **Tree-sitter path**: Extracts raw import strings from the AST, then resolves them against
  the file manifest using language-specific heuristics (relative path resolution, module path
  conventions). Unresolvable imports are classified as external and excluded.

- **LLM fallback path**: The LLM receives the file content and the file manifest. It returns
  resolved project file paths directly — no separate resolution step needed.

The Graph Builder receives uniformly resolved dependencies from either path. It does not need
the file manifest and does not know which extraction method was used.

### State persistence model

**`.docai/` directory** (Option B) in the project root, containing:
- `manifest.json` — file manifest snapshot with classifications and content hashes
- `analyses/` — one JSON file per source file containing its FileAnalysis
- `graph.json` — dependency graph and processing order
- `purposes.json` — Pass 1 file purposes
- `status.json` — generation status per file
- Generated documentation output (directory structure mirroring source tree)

This supports atomic per-file updates, crash recovery, and incremental regeneration without
risking corruption of unrelated data.

## Consequences

### Positive
- Six components with clear responsibilities and well-defined data flow boundaries
- Import resolution asymmetry between tree-sitter and LLM paths is fully encapsulated in the
  Structure Extractor — no other component needs to know about it
- Disk-backed state store supports all three persistence motivations: crash recovery,
  incremental regeneration, and memory efficiency
- `.docai/` directory structure allows atomic per-file updates and survives partial failures
- Each component is independently testable: Discovery with test directory trees, Structure
  Extractor with test source files, Graph Builder with test dependency lists, etc.
- Pipeline architecture is simple to reason about and debug — data flows in one direction
  through well-defined stages
- Python + uv is a pragmatic choice that optimizes for solo developer productivity

### Negative / Trade-offs accepted
- Six components is more structure than a "just get it working" prototype needs. Accepted
  because the pipeline's stateful nature and crash recovery requirements demand clear
  boundaries from the start — retrofitting them would be harder.
- The Structure Extractor is the most complex component (three extraction paths, import
  resolution, entity taxonomy mapping). It will need internal sub-module organization as it
  grows.
- Language-specific import resolution heuristics inside the Structure Extractor will
  accumulate over time as more languages are supported. This is manageable complexity —
  each language's resolver is independent.
- The `.docai/` directory adds filesystem management complexity and needs a migration strategy
  if the format changes between docai versions.

### Constraints created
- Need to design the Project State serialization format (JSON schemas for each stored artifact)
- Need to define the Structure Extractor's internal architecture (how tree-sitter, LLM
  fallback, and import resolution are organized as sub-modules)
- Need to design the Documentation Generator's prompt templates and context assembly algorithm
- Need to decide on the LLM client abstraction (direct Anthropic SDK, litellm, or a thin
  wrapper that supports provider switching)
- Need to define the CLI command interface (subcommands, flags, configuration file)

## Open Questions

1. **Import resolution heuristics**: Which languages get dedicated import resolution logic
   in v1, and how sophisticated does it need to be? Python and JavaScript/TypeScript are
   likely first priorities. Others may fall back to the LLM path for both extraction and
   resolution.

2. **Project State migration**: When the `.docai/` format changes between docai versions,
   how is migration handled? Options range from "delete and regenerate" to versioned schemas
   with migration scripts.

3. **LLM client abstraction**: Should docai support multiple LLM providers from v1, or
   start with a single provider (Anthropic) and add abstraction later? Starting narrow is
   simpler but switching later requires refactoring the Documentation Generator.

4. **Parallelism**: The current design describes a sequential pipeline. Structure extraction
   is embarrassingly parallel (per-file, independent). Documentation generation is partially
   parallelizable (files at the same depth in the dependency graph can be documented
   concurrently). Is parallelism a v1 concern or a future optimization?

5. **Output directory structure**: Where does generated documentation live relative to the
   project? Inside `.docai/docs/`? A separate `docs/` directory? Configurable?
