# ADR-010: Documentation Generator Component Design

## Status
Accepted

## Context
ADR-006 established the Documentation Generator as the fourth pipeline component — responsible
for orchestrating LLM calls to produce the actual documentation output. ADR-002 defined the
three-pass pipeline (static analysis → orientation sweep → detailed documentation), the hybrid
output format (YAML frontmatter + narrative + per-entity reference), and the context assembly
strategy. ADR-004 defined what to document per entity category. ADR-009 defined the
ProcessingPlan (bucket-based level ordering) that determines execution order.

This ADR defines the Documentation Generator's internal design: how context is assembled per
file, how Pass 1 and Pass 2 work, how per-file and per-entity documentation modes interact,
how the output is structured, and how the LLM client is abstracted.

### Key design considerations

- **Context quality determines documentation quality**: The LLM can only document what it
  understands. The right context — project purpose, directory context, file purpose, source
  code, dependency information — is the single most important factor in output quality.
- **Cost efficiency**: LLM calls are the pipeline's primary cost. The context assembly must
  be precise (include what matters, exclude what doesn't) and the per-file vs. per-entity
  split must avoid unnecessary calls.
- **Output reliability**: The hybrid output format includes machine-readable YAML frontmatter.
  LLMs are unreliable at producing valid structured data. The generation strategy must account
  for this.
- **Provider flexibility**: The LLM client must support switching providers without
  restructuring the Documentation Generator.

## Options Considered

### Context assembly strategy

#### Option A: Include full documentation for all dependencies
- **Pros**: Maximum information available to the LLM
- **Cons**: Wasteful — most dependency entities aren't referenced by the current file. Blows
  context window for files with many dependencies. Expensive in tokens.

#### Option B: Include only referenced entities from dependencies
- **Pros**: Focused, efficient. The LLM gets deep context for what the file actually uses
  and a name-level overview of what else is available. Token-efficient.
- **Cons**: The entity name matching heuristic may have false positives (short names matching
  unrelated occurrences). Acceptable for v1.

### Per-file vs. per-entity documentation

#### Option A: Per-file only (all entities documented in one call)
- **Pros**: Simplest. Module-level narrative is naturally coherent. Fewer LLM calls.
- **Cons**: Quality degrades for files with many entities — later entities in the response
  get less thorough treatment.

#### Option B: Per-entity only (one call per entity)
- **Pros**: Each entity gets focused attention
- **Cons**: No coherent module-level narrative. Dramatically more LLM calls. Loses the
  "how do these pieces fit together" perspective.

#### Option C: Hybrid — per-file call for overview + per-entity follow-ups for qualifying entities
- **Pros**: Module-level coherence from the per-file call. Depth for complex entities from
  follow-ups. Balanced cost — follow-ups only for entities that benefit from deeper treatment.
- **Cons**: Two-phase generation adds complexity. Need a merging step to combine per-file
  and per-entity outputs.

### YAML frontmatter generation

#### Option A: LLM generates the complete output including YAML frontmatter
- **Pros**: Single generation step, no post-processing
- **Cons**: LLMs frequently produce invalid YAML — wrong indentation, unquoted strings,
  missing fields. Requires validation and retry logic. Unreliable.

#### Option B: Programmatic frontmatter assembly, LLM generates prose only
- **Pros**: Frontmatter data already exists (entity directories from Structure Extractor,
  dependency lists from Graph Builder, content hashes from Discovery). Assembling it
  programmatically is deterministic and always valid. The LLM focuses on what it's good
  at: writing documentation prose.
- **Cons**: Requires a stitching step to combine programmatic frontmatter with LLM prose.
  Straightforward implementation.

### LLM client abstraction

#### Option A: Direct provider SDK, no abstraction
- **Pros**: Simplest, no wrapper overhead
- **Cons**: Switching providers requires changes throughout the Documentation Generator

#### Option B: Thin wrapper around the call interface
- **Pros**: Provider switching is a contained change (swap the wrapper implementation).
  The Documentation Generator calls a uniform interface (send prompt, get response).
  No heavyweight abstraction framework.
- **Cons**: Must be designed carefully to not leak provider-specific assumptions

#### Option C: Multi-provider framework (litellm or similar)
- **Pros**: Immediate access to many providers
- **Cons**: Heavy dependency for a feature that isn't needed yet. Adds complexity and a
  potential point of failure. Can always be adopted later.

## Decision

### LLM client abstraction

**Thin wrapper around the call interface** (Option B). The Documentation Generator interacts
with the LLM through a minimal interface:

```
LLMClient:
  async send(prompt: str, system: str | None) -> str
  async send_structured(prompt: str, system: str | None, schema: dict) -> dict
```

The v1 implementation wraps the **Google GenAI SDK**. The wrapper handles:
- API key management
- Rate limiting and retry logic (exponential backoff)
- Token counting for cost tracking and logging
- Error classification (retryable vs. fatal)

Provider switching means implementing a new wrapper class with the same interface. The
Documentation Generator never imports or references the provider SDK directly.

### Pass 1: Orientation sweep

A single LLM call (or batched for large projects) that produces a one-sentence purpose for
every file and every directory in the project. This runs before any bucket processing begins.

**Input to the LLM:**
- User's project description
- Complete project tree (file paths and directory structure)
- Entity directories for all files (entity names and categories only — no signatures, no
  line ranges, no source code). This is compact: just a list of "file X contains: function
  foo, class Bar, constant MAX_SIZE."

**Output from the LLM:**
- One-sentence purpose per file
- One-sentence purpose per directory

**Cost**: ~1-2% of total pipeline budget. The input is compact (names and categories, not
source code) and the output is short (one sentence per file/directory).

**Directory purposes** are generated alongside file purposes in the same call. This solves
the timing problem identified during context assembly discussion: when documenting a file,
we want its parent directory's purpose as context, but package summaries are generated after
their constituent files. Pass 1 directory purposes provide this context cheaply without
depending on the package summary generation order.

**Large project batching**: If the project tree + entity directories exceed the context window
for a single Pass 1 call, batch by top-level directory. Each batch includes the full project
tree (for orientation) but only the entity directories for files in that batch's directories.
The project tree provides global context while keeping the per-batch payload manageable.

### Pass 2: Detailed documentation

Process buckets from the ProcessingPlan in order. For each bucket, fire all work items
concurrently (asyncio). Three work item types, three documentation strategies:

#### Source file documentation

**Context assembly per source file:**

```
1. Project description (user-provided, one sentence)
2. Directory context (purpose sentences for all parent directories, from Pass 1)
3. File purpose (from Pass 1, one sentence)
4. Full source code of the file being documented
5. For each direct project dependency:
   a. Module purpose sentence (from Pass 1)
   b. Complete entity name list (names only — compact overview of what the
      dependency offers)
   c. Full documentation for referenced entities only
      - An entity is "referenced" if its name (lowercased) appears anywhere
        in the current file's source code (lowercased)
      - If generated docs exist for the dependency: include the entity's
        documentation section
      - If no generated docs exist (cycle fallback): include the entity's
        raw source code from the dependency file
```

**No truncation strategy.** The full context is assembled as designed. Modern LLM context
windows (100K-200K tokens) are sufficient for the vast majority of files. If a file's
assembled context is unusually large (exceeding a configurable warning threshold), a warning
is emitted to the user indicating that documentation quality may be affected. If the context
exceeds the model's actual limit, the LLM API returns an error, which is logged and the file
is marked as failed in Project State.

**Entity name matching**: Lowercase string comparison. All entity names from the dependency's
entity directory are lowercased and checked against the lowercased source code of the current
file. No minimum length filter — kept simple for v1. False positives (short names matching
unrelated text) are acceptable; the cost is slightly more context included, not incorrect
documentation.

#### Per-file vs. per-entity documentation mode

**Default: per-file mode.** One LLM call per source file produces:
- Module-level narrative overview (how the file's parts fit together)
- Documentation for all entities in the file

**Large file mode: per-file + per-entity follow-ups.** Triggered when the entity count in a
file exceeds a configurable threshold (default: 15 entities, configurable via project config
file).

When triggered:

1. **Per-file call**: Produces module-level narrative overview + brief summaries for all
   entities. This establishes coherence and the "big picture" of the file.

2. **Entity filtering**: Identify entities that qualify for follow-up calls based on entity
   category:
   - **Follow-up**: Callables (functions, methods, constructors, closures), Types (classes,
     structs, enums, interfaces, traits), Implementations (trait impls, interface impls)
   - **No follow-up**: Values (constants, module-level variables, config), simple type aliases.
     The per-file call's treatment is sufficient for these.

3. **Per-entity follow-up calls**: For each qualifying entity, a focused call that receives:
   - Module overview from step 1 (for coherence — the entity is documented in context of
     the whole file)
   - The entity's source code (extracted by line range from the Structure Extractor)
   - Relevant dependency context (same assembly as the per-file call)
   - Entity documentation standards from ADR-004 for the entity's category

4. **Merge**: Replace the brief entity summaries from step 1 with the detailed documentation
   from step 3. The module-level narrative from step 1 is preserved as-is.

The category-based filtering avoids language-specific complexity metrics. Entity categories
come directly from the Structure Extractor's FileAnalysis — no additional analysis needed.

#### Config file documentation

Config files (Dockerfiles, Makefiles, CI configs, docker-compose, Terraform, SQL migrations)
receive a single LLM call producing a module-level summary only.

**Context:**
- Project description
- File purpose from Pass 1
- Full file content

**Output:** A concise overview of what the file configures, what the key settings are, and
what a developer would need to know or change. No entity extraction, no per-entity
documentation.

#### Package summary documentation

Package summaries are generated for directories containing documented files. Triggered by
`package_summary` work items in the ProcessingPlan.

**Context:**
- Project description
- Directory purpose from Pass 1
- List of all files in the directory with their file-level purpose sentences
- Generated module-level overviews for all files in the directory
- Child package summaries (for directories containing subdirectories)

**Output:** A package-level overview explaining:
- What the package/directory provides
- How its files work together
- Key entry points and public APIs
- Relationships to other packages

### Output format

Each documented file produces a markdown file with the hybrid format from ADR-002:

**YAML frontmatter** — assembled programmatically (Option B), never generated by the LLM:
```yaml
---
file: src/parser.py
module_purpose: "Converts raw markdown into structured Document objects"
depends_on:
  - file: src/models.py
    imports: [Document, Section, CodeBlock]
  - file: src/config.py
    imports: [ParserConfig]
entities:
  - category: Callable
    name: parse_file
    visibility: public
  - category: Callable
    name: parse_string
    visibility: public
  - category: Type
    name: MarkdownParser
    visibility: public
generated: 2026-03-28T14:30:00Z
source_hash: a1b2c3d4e5f6
extraction_method: tree-sitter
parse_errors: false
---
```

**Narrative body** — generated by the LLM:
- Module overview (prose explaining what the file does and how its parts work together)
- Per-entity reference sections (documentation per ADR-004 standards for each entity category)

The frontmatter data comes from: file path (Discovery), module purpose (Pass 1), dependencies
(Structure Extractor → Graph Builder), entity list (Structure Extractor), timestamps (current
time), source hash (Discovery manifest), extraction method and parse errors (Structure
Extractor FileAnalysis).

### Completeness verification

After generating documentation for a source file (whether per-file or per-file + per-entity),
compare the entities documented in the LLM's output against the entity directory from the
Structure Extractor:

1. Parse the LLM output to extract documented entity names
2. Compare against the FileAnalysis entity list
3. For any missing entities: make a targeted follow-up call with the entity's source code
   and the module overview as context
4. Append the follow-up documentation to the output

This catches cases where the LLM skips an entity (common with large files) without requiring
a full regeneration. The verification uses entity names from the Structure Extractor as the
source of truth.

### Configuration

The following Documentation Generator settings are configurable via the project config file
(format TBD in CLI/Orchestrator ADR, likely TOML):

| Setting | Default | Description |
|---------|---------|-------------|
| `per_entity_threshold` | 15 | Entity count above which per-entity follow-up calls are triggered |
| `context_warning_threshold` | 80000 | Token count above which a large-context warning is emitted |
| `model` | (provider default) | LLM model identifier |
| `max_concurrent_calls` | 5 | Maximum concurrent LLM calls per bucket |
| `project_description` | (prompted on first run) | One-sentence project description |

`max_concurrent_calls` limits concurrency within a bucket to avoid API rate limiting. This
is the Documentation Generator's concern, not the Graph Builder's — buckets can have many
items but the generator controls how many run simultaneously.

## Consequences

### Positive
- Context assembly is precise — includes what matters (referenced entities, dependency
  overviews, directory context) without unnecessary bulk
- No truncation simplifies the implementation and avoids quality degradation from dropped
  context. Warnings keep the user informed.
- Programmatic YAML frontmatter eliminates the unreliable-LLM-output problem entirely —
  frontmatter is always valid, always complete
- Per-file + per-entity hybrid preserves module-level coherence while adding depth for
  complex entities in large files
- Category-based entity filtering for follow-ups is language-independent — no fragile
  complexity metrics
- Thin LLM client wrapper enables provider switching without restructuring the generator
- Completeness verification catches missed entities without full regeneration
- Directory purposes from Pass 1 solve the timing problem for parent directory context
- Configurable thresholds let users tune behavior to their projects

### Negative / Trade-offs accepted
- No truncation means a truly enormous file (hundreds of dependencies, thousands of
  referenced entities) could exceed the model's context window. In practice this is
  vanishingly rare and indicates a code structure problem. The error is surfaced to the
  user, not silently handled.
- Entity name matching via lowercase string comparison will produce false positives for
  short, common names. The cost is slightly more context included — not incorrect
  documentation. Acceptable for v1.
- Category-based filtering for per-entity follow-ups treats all Callables equally — a
  trivial getter gets a follow-up call if the file exceeds the threshold. The cost of
  unnecessary follow-ups is small (short entities produce short responses), and avoiding
  per-entity complexity analysis keeps the implementation simple.
- Starting with Google GenAI SDK means Anthropic, OpenAI, and other providers aren't
  available out of the box. The thin wrapper makes adding them a contained task.

### Constraints created
- Need to design the LLM prompt templates for: Pass 1 orientation sweep, per-file
  documentation, per-entity follow-up documentation, config file summarization, package
  summary generation
- Need to design the output parsing logic that extracts documented entity names for
  completeness verification
- Need to define the project config file format and location (CLI/Orchestrator ADR)
- Need to implement the LLM client wrapper interface and Google GenAI implementation
- Need to define the warning/error reporting strategy for context size issues and
  failed generation attempts

## Open Questions

1. **Pass 1 batching threshold**: At what project size does Pass 1 need batching? How
   should batches be structured — by top-level directory, by file count, by estimated
   token count? Needs experimentation with real projects.

2. **Completeness verification parsing**: How does the Documentation Generator reliably
   parse entity names from the LLM's prose output? Regex matching against known entity
   names from the FileAnalysis? Heading-level parsing (each entity gets its own heading)?
   The LLM could be instructed to use a consistent heading format that's easy to parse.

3. **Cost tracking and reporting**: Should docai track and report estimated LLM costs per
   run? This would help users understand the cost implications of their projects and
   configuration choices. Requires token counting per call and a cost-per-token estimate
   per model.

4. **Retry strategy for failed LLM calls**: How many retries for transient failures?
   Should the Documentation Generator retry with a simplified prompt (less context) if
   the full context consistently fails? Or just mark the file as failed and move on?

5. **Package summary threshold**: Should every directory get a package summary, or only
   directories with multiple documented files? A directory with a single source file
   probably doesn't need a separate package summary. Deferred for implementation-time
   decision.
