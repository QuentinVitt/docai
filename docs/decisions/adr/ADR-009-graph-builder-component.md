# ADR-009: Graph Builder Component Design

## Status
Accepted

## Context
ADR-006 established the Graph Builder as the third pipeline component — responsible for
consuming resolved dependencies from the Structure Extractor, building the project-wide
dependency graph, and determining the processing order for documentation generation. ADR-008
defined the FileAnalysis output that serves as the Graph Builder's input, with uniformly
resolved dependency paths regardless of extraction method.

This ADR defines the Graph Builder's concrete design: how it constructs the dependency graph,
how it determines processing order, how it handles dependency cycles, and how it integrates
package/directory-level documentation scheduling.

### Key design considerations

- **Concurrency**: LLM calls are the pipeline's bottleneck — I/O-bound and expensive. The
  processing order must enable concurrent execution. Files with no mutual dependencies should
  be processable simultaneously.
- **Package-level documentation**: ADR-001 established level 4 (package/directory) as a
  documentation target. Package summaries are rollups of file-level docs and can only be
  generated once all files in the package have been documented. The processing order must
  account for this.
- **Dependency cycles**: Real codebases contain circular imports. The Graph Builder must
  detect these and produce a processing order that handles them gracefully without doubling
  LLM costs.
- **Config file scheduling**: Config files (from ADR-005/007) bypass the Structure Extractor
  and have no dependencies. They need to appear in the processing order as independent work
  items.

## Options Considered

### Processing order representation

#### Option A: Flat topological sort
A single ordered list of files, leaves first, dependents later.
- **Pros**: Simple, well-understood algorithm
- **Cons**: Doesn't expose parallelism opportunities. The Documentation Generator would need
  to determine which files can be processed concurrently by inspecting the graph itself.
  Mixes the "what order" question with the "what's parallelizable" question.

#### Option B: Bucket-based level ordering
Files grouped into buckets (tiers). All files in a bucket have their dependencies fully
satisfied by earlier buckets. Every file within a bucket can be processed concurrently.
- **Pros**: Parallelism is explicit in the output. The Documentation Generator processes
  one bucket at a time, firing all items in a bucket concurrently, then moving to the next.
  Simple execution model.
- **Cons**: Slightly more complex to compute than a flat topological sort. Some files in a
  bucket may finish faster than others, leaving resources idle until the whole bucket
  completes. (Acceptable for v1 — fine-grained scheduling is a future optimization.)

### Cycle handling

#### Option A: Two-pass documentation for all cycle members
Document every file in a cycle twice — first with entity directory context only, then with
full docs from the first pass.
- **Pros**: Both files in a cycle get full documentation context on the second pass.
  Symmetric treatment.
- **Cons**: Doubles the LLM calls for every file in every cycle. Cycles may be rare in
  practice, making this an expensive mechanism that rarely fires. Adds orchestration
  complexity for the Documentation Generator.

#### Option B: Deliberate cycle breaking — document one file first with entity directory context
Break the cycle by placing one file in an earlier bucket (documented with entity directory
entries for its cycle partners as lightweight context) and the other in a later bucket
(documented with full generated docs for its dependency). The file with fewer cross-cycle
dependencies goes first, since it loses the least context.
- **Pros**: No extra LLM calls. Simple bucket assignment. The file documented first still
  gets structural context (entity names, signatures, categories) — just not the full
  narrative docs. Good enough for most cases.
- **Cons**: Asymmetric documentation quality — the file documented first may have slightly
  less rich dependency descriptions. Acceptable trade-off for v1.

### Package summary scheduling

#### Option A: Separate pass after all files are documented
Run a dedicated pass after all file-level documentation to generate package summaries.
- **Pros**: Simple, all file docs guaranteed available
- **Cons**: Misses the opportunity to generate package summaries as soon as they're ready.
  Adds a distinct pipeline phase.

#### Option B: Inline scheduling — package summary enters the bucket after its last file
When the last file in a directory is scheduled in bucket N, the package summary for that
directory is scheduled in bucket N+1 (or in bucket N if no later files depend on it).
- **Pros**: Package summaries are generated as soon as possible. Natural fit with the bucket
  model — they're just another work item. Enables downstream files to reference package-level
  context if needed.
- **Cons**: Requires tracking which directories have all their files scheduled and in which
  bucket the last one lands.

## Decision

### Processing order: bucket-based level ordering (Option B)

The Graph Builder produces a **ProcessingPlan** consisting of ordered buckets. Each bucket
contains work items that can be processed concurrently. A bucket's items are only scheduled
once all their dependencies (in earlier buckets) are satisfied.

### Bucket assignment algorithm

1. **Build the file-level dependency graph** from FileAnalysis results. Nodes are source files.
   Directed edges: A → B means A imports from B.

2. **Detect strongly connected components (SCCs)** using Tarjan's algorithm. SCCs with more
   than one node are dependency cycles.

3. **Break cycles** by selecting the file with fewest cross-cycle dependencies (the file that
   imports the least from other cycle members) to be documented first. This file is assigned
   to an earlier bucket with entity directory context for its cycle partners. The remaining
   cycle members are assigned to later buckets normally, where they'll have the first file's
   full docs available. Cycle breaking decisions are recorded in the output for transparency
   and diagnostic purposes.

4. **Compute bucket assignment** via level-based topological sort on the (now acyclic) graph:
   - Bucket 0: all files with no dependencies (leaf files, isolated files) + all config files
   - Bucket 1: files whose dependencies are all in bucket 0
   - Bucket N: files whose dependencies are all in buckets 0 through N-1

5. **Schedule package summaries**: For each directory containing documented files, determine
   the highest bucket index among its files. Schedule the package summary in the next bucket
   (index + 1). If a directory contains subdirectories with their own package summaries,
   the parent directory's summary is scheduled after all child summaries.

6. **Nested directory ordering**: Package summaries follow a bottom-up order within the
   directory tree. `src/parsing/` gets its summary before `src/` gets its summary, because
   the `src/` summary should reference the `src/parsing/` package description.

### Work item types

The ProcessingPlan contains three types of work items:

| Type | Description | Context available |
|------|-------------|-------------------|
| **source_file** | Source code file for full documentation pipeline | Entity directory, dependency docs from earlier buckets |
| **config_file** | Code-like config file for module-level summary | File content only (no entity directory, no dependencies) |
| **package_summary** | Directory/package-level documentation | All file-level docs and child package summaries within the directory |

### Output contract

```
ProcessingPlan:
  buckets:                          # ordered list of concurrent execution tiers
    - bucket_index: int             # 0-based tier index
      items:                        # work items in this bucket (all parallelizable)
        - type: str                 # source_file | config_file | package_summary
          path: str                 # file path or directory path
  dependency_graph:                 # the raw graph for reference and debugging
    nodes: list[str]                # file paths
    edges: list[(str, str)]         # (from, to) directed edges
  cycles:                           # detected cycles and how they were resolved
    - files: list[str]              # files in the cycle
      broken_by: str                # file documented first (placed in earlier bucket)
      reason: str                   # why this file was chosen (e.g., "fewest cross-cycle imports")
```

The `dependency_graph` and `cycles` fields are preserved for debugging and diagnostics.
The `buckets` list is the actionable output consumed by the Documentation Generator.

### Config file handling

Config files are placed in **bucket 0** alongside leaf source files. They have no dependencies
and produce no output that other files consume. Processing them in the first bucket means they
run concurrently with the initial batch of source files, maximizing throughput.

### Concurrency model

The bucket model is designed for **asyncio-based concurrency**. The Documentation Generator
processes one bucket at a time:

1. Fire all LLM calls for items in the current bucket concurrently (asyncio.gather or similar)
2. Wait for all items in the bucket to complete
3. Save results to Project State
4. Move to the next bucket

This is the natural fit for the pipeline's bottleneck (I/O-bound LLM API calls). Tree-sitter
parsing during Structure Extraction is CPU-bound but fast enough (milliseconds per file) that
parallelizing it is not a v1 concern.

Fine-grained scheduling (starting bucket N+1 items as soon as their specific dependencies
in bucket N complete, rather than waiting for the entire bucket) is a future optimization.
The bucket-at-a-time model is simpler and sufficient for v1.

### Cycle context model

Cycles do not require special handling in the context assembly logic. The context builder
follows one universal rule for every dependency of every file:

1. Check if generated documentation exists for the dependency (in Project State)
2. If yes → include the generated documentation as context
3. If no → include the dependency's raw source code + entity directory entries as context

This rule applies uniformly to all files. For normal (non-cycle) dependencies, generated
docs will always be available because the bucket ordering guarantees dependencies are
documented first. For cycle dependencies where the partner hasn't been documented yet,
the context builder naturally falls through to raw source code — no cycle-detection logic,
no special flags, no separate code path.

The quality difference is minimal. The LLM receives the full source code of the dependency
either way — either preprocessed into structured documentation or as raw code. Since reading
and understanding raw source code is docai's core premise, the LLM is fully equipped to
work with either form.

This is a deliberate architectural outcome: the Graph Builder breaks cycles for bucket
ordering purposes, and the context builder's universal fallback rule handles the consequence
transparently. If cycle documentation quality ever becomes a concern, two-pass documentation
can be added as a future enhancement without changing the bucket model or context assembly
logic.

## Consequences

### Positive
- Bucket model makes parallelism explicit and simple to execute — no complex scheduling logic
  in the Documentation Generator
- Cycle breaking avoids doubling LLM costs while providing full source code context for
  files documented before their cycle partners — minimal quality difference from normal flow
- Package summaries are scheduled naturally within the bucket model, generated as soon as
  all their constituent files are documented
- Config files are handled cleanly as independent work items in the first bucket
- The dependency graph and cycle information are preserved for debugging
- asyncio-based concurrency matches the I/O-bound bottleneck (LLM API calls) without
  introducing threading or multiprocessing complexity

### Negative / Trade-offs accepted
- Bucket-at-a-time execution may leave resources idle when some items in a bucket finish
  before others. Acceptable for v1 — fine-grained scheduling is a future optimization.
- Cycle breaking produces slightly asymmetric context — the file documented first gets raw
  source code instead of structured docs for its cycle partner. In practice the LLM handles
  raw source well, so the quality difference is minimal. Two-pass can be added later if needed.
- Package summary scheduling adds logic to track directory membership and determine when all
  files in a directory have been processed. This is straightforward bookkeeping but adds to
  the Graph Builder's responsibilities.

### Constraints created
- The Documentation Generator must understand the three work item types and handle each
  appropriately (full pipeline for source files, module-level summary for config files,
  rollup summary for package summaries)
- The Documentation Generator's context assembly follows one universal rule: for each
  dependency, include generated docs if available, otherwise include raw source code +
  entity directory entries. No cycle-specific logic needed — the fallback handles it
  naturally.
- Need to define which directories get package summaries (every directory with source files?
  only directories with 2+ files? configurable?) — deferred to Documentation Generator ADR

## Open Questions

1. **Package summary threshold**: Should every directory with source files get a package
   summary, or only directories with multiple files? A directory containing a single
   `__init__.py` probably doesn't need its own summary. A threshold (e.g., 2+ documented
   files) may be appropriate but needs validation against real projects.

2. **Monorepo support**: In monorepos with multiple independent packages under one root,
   should the Graph Builder detect package boundaries (e.g., separate `package.json` or
   `pyproject.toml` files) and treat them as independent subgraphs? This would affect both
   the dependency graph (no cross-package edges) and package summary scheduling. Deferred
   to future enhancement.

3. **Bucket size limits**: Should there be a maximum number of concurrent LLM calls per
   bucket to avoid rate limiting? This is more of a Documentation Generator concern but
   affects how buckets are consumed. The Graph Builder could optionally split large buckets
   into sub-buckets with a configurable concurrency limit.
