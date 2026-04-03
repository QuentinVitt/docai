# ADR-002: Analysis Pipeline, Context Management, Output Format, and Regeneration

## Status
Accepted

## Context
Following the domain and scope decisions in ADR-001, several open technical questions needed
resolution before moving to system architecture: how to extract code structure across languages,
what the generated documentation looks like, how to order the analysis pipeline, how to manage
LLM context windows efficiently, and how to avoid regenerating unchanged documentation.

These decisions are tightly coupled — the pipeline ordering determines what context is available,
which shapes the output format, which in turn affects the regeneration strategy.

## Options Considered

### Structure Extraction Method

#### Option A: Tree-sitter only
- **Pros**: Fast, accurate ASTs for ~200 languages, deterministic
- **Cons**: No fallback for unsupported languages or DSLs

#### Option B: LLM-only analysis
- **Pros**: Truly universal, understands any language
- **Cons**: Slow, expensive, non-deterministic, harder to get precise entity boundaries

#### Option C: Tree-sitter with LLM fallback
- **Pros**: Fast and accurate for common languages, universal coverage via fallback, best of
  both worlds
- **Cons**: Two code paths to maintain, LLM fallback produces lower-fidelity structural data
  than tree-sitter

### Output Format

#### Option A: Flat reference (per-entity API docs)
- **Pros**: Easy to look up a specific function, familiar format (like Rustdoc/Sphinx output)
- **Cons**: Doesn't explain how pieces work together, poor for "help me understand this file"

#### Option B: Narrative prose (reads like a guide)
- **Pros**: Best matches the core pain point of understanding unfamiliar code, readable
  top-to-bottom
- **Cons**: Hard to use as quick reference, hard for machines to parse for future features
  (GraphRAG, onboarding assistant)

#### Option C: Structured with YAML frontmatter (machine-readable + human-readable)
- **Pros**: YAML metadata supports tooling (dependency tracking, regeneration, future
  GraphRAG), tables make signatures scannable
- **Cons**: Reads mechanically, less pleasant as a comprehension aid

#### Option D: Hybrid — structured frontmatter + narrative body + per-entity detail
- **Pros**: Machine-readable metadata for tooling, narrative module overview for comprehension,
  per-entity detail for reference. Serves both humans and future features.
- **Cons**: Most complex to generate, LLM must produce structured frontmatter reliably

### Pipeline Ordering

#### Option A: Pure bottom-up (leaf files first)
- **Pros**: Smaller context per call, cheaper, each file's docs built on verified dependency
  docs
- **Cons**: LLM lacks big-picture project context, may produce generic documentation that
  doesn't reflect the file's role in the project

#### Option B: Pure top-down (entry points first)
- **Pros**: Every piece of documentation written with project purpose in mind
- **Cons**: Larger context per call (no dependency docs available yet), more expensive

#### Option C: Three-pass hybrid (static analysis → orientation sweep → bottom-up detail)
- **Pros**: Combines big-picture awareness (cheap orientation pass) with focused, efficient
  bottom-up generation. Static analysis is free. Orientation pass costs ~1-2% of total budget
  while meaningfully improving every subsequent call.
- **Cons**: More pipeline stages to implement and orchestrate

### Documentation Granularity

#### Option A: One LLM call per entity (function/class)
- **Pros**: Laser-focused context, easy retry/regeneration of single entities, maximally
  precise cache invalidation
- **Cons**: 4x+ more API calls (latency, rate limits), loses intra-file narrative coherence,
  module-level docs can't be written without seeing the whole file

#### Option B: One LLM call per file
- **Pros**: LLM sees all entities together, can write coherent module-level overview,
  fewer calls
- **Cons**: Large files may produce uneven quality, one changed function regenerates all docs
  for the file

#### Option C: Per-file default with per-entity fallback for large files
- **Pros**: Coherent module-level docs in the common case, graceful handling of large files,
  tree-sitter verification catches any missed entities for targeted follow-up calls
- **Cons**: Two modes to implement, need a threshold heuristic for switching

### Regeneration Strategy

#### Option A: Regenerate everything on each run
- **Pros**: Simple, always correct
- **Cons**: Expensive, wasteful for large projects with small changes

#### Option B: Content-hash-based caching with dependency tracking
- **Pros**: Only regenerates what changed, precise invalidation via transitive dependency
  hashes
- **Cons**: Must track dependency graph and hashes between runs, cache can become stale if
  tracking is imprecise

## Decision

**Structure extraction**: Option C — tree-sitter as the primary parser with LLM as fallback.
Tree-sitter handles the common case (fast, accurate), and the LLM covers unsupported languages.
The pipeline must handle both quality levels of structural data gracefully.

**Output format**: Option D — hybrid format combining:
- YAML frontmatter with machine-readable metadata (file path, module purpose, dependencies,
  entity list, source hash, generation timestamp)
- Narrative module-level overview explaining what the file does and how its parts fit together
- Per-entity reference sections with signatures, parameters, relationships, and behavior

This serves both the human comprehension use case (narrative body) and future tooling needs
(structured frontmatter for GraphRAG, dependency tracking, regeneration).

**Pipeline ordering**: Option C — three-pass hybrid:
- **Pass 0 (static analysis, no LLM)**: Tree-sitter parses all files. Extracts imports,
  function signatures, class definitions, type definitions. Builds dependency graph, entity
  directory per file, detects cycles. Output: project structure map, dependency graph, entity
  directories.
- **Pass 1 (orientation sweep, cheap LLM)**: Single LLM call (or batched for large projects)
  with the user's project description, the project tree, and entity directories from Pass 0
  (entity names + signatures, not full source). Produces a one-sentence purpose for each file.
  Cost: ~1-2% of total pipeline budget.
- **Pass 2 (detailed documentation, main LLM cost)**: Process files in dependency order
  (leaves first). For each file, context includes: project description, file purpose from
  Pass 1, full source code, already-generated docs for dependencies (or entity directory
  entries if not yet generated). Tree-sitter verifies completeness after generation; targeted
  follow-up calls fill any gaps.

**Documentation granularity**: Option C — per-file as the default, with per-entity fallback
for large files (threshold to be determined, likely 15-20+ entities). Tree-sitter serves as a
post-generation verification step: compare entities found by tree-sitter against entities
documented by the LLM, make targeted follow-up calls for anything missing.

**Regeneration**: Option B — content-hash-based caching stored in a `.docai` metadata file
in the project root. Tracks:
- Content hash per source file
- Transitive dependency hashes (a file's docs are valid only if its own hash AND all
  dependencies' hashes match)
- Entity directory snapshots for precise invalidation

Uses content hashes (not timestamps) for deterministic behavior across git branch switches.

**Circular dependencies**: Handled via two-pass documentation — first pass documents each
file in the cycle using only entity directory entries for the other files in the cycle (no
full docs available yet). The context builder remains uniform: if docs exist for a dependency,
include them; if not, include the entity directory entry. Files in cycles may have an agent-like
ability to read other files if the entity directory is insufficient.

## Consequences

### Positive
- Three-pass pipeline gives big-picture awareness at negligible cost while keeping detailed
  generation focused and efficient
- Hybrid output format serves both human comprehension and machine consumption, directly
  supporting future features (GraphRAG, onboarding assistant, architecture diagrams)
- Per-file documentation preserves narrative coherence — the most valuable aspect for the
  "I don't understand this code" use case
- Tree-sitter verification ensures completeness without relying solely on the LLM
- Hash-based regeneration with dependency tracking minimizes expensive LLM calls on subsequent
  runs
- Circular dependency handling is uniform with the normal flow (entity directory as fallback
  context)

### Negative / Trade-offs accepted
- Three pipeline passes add orchestration complexity
- Two documentation modes (per-file and per-entity) need implementation and a switching
  heuristic
- The LLM fallback for structure extraction will produce lower-fidelity data than tree-sitter,
  meaning documentation quality may vary by language
- YAML frontmatter adds generation complexity — the LLM must produce structured output
  reliably, may need post-processing or template-based generation for the frontmatter
- Dependency tracking for cache invalidation adds state management complexity

### New constraints created
- Need to design the `.docai` cache file format
- Need to define the YAML frontmatter schema
- Need to determine the entity-count threshold for switching from per-file to per-entity mode
- Need to design the context assembly algorithm (which entities to include, how to truncate
  for very large dependency chains)
- Need to decide how Pass 1 batches for projects too large for a single orientation call

## Open Questions

1. **Context assembly precision**: The current plan uses regex matching to check if an entity
   name from a dependency appears in the current file. This may need refinement — common names
   could produce false positives, and indirect usage (e.g., a type used only in a type
   annotation) might be missed.

2. **Large project scaling**: At what project size does Pass 1 need batching? How should
   batches be structured (by directory, by dependency cluster)?

3. **LLM output reliability for frontmatter**: Can the LLM reliably produce valid YAML
   frontmatter, or should frontmatter be generated programmatically from Pass 0 data with
   only the prose sections coming from the LLM?
