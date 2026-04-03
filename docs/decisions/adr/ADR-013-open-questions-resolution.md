# ADR-013: Resolution of Open Questions from System Architecture ADRs

## Status
Accepted

## Context
ADRs 006-012 defined the system architecture and component designs for docai. Each ADR
identified open questions that needed resolution before implementation. This ADR consolidates
and resolves all remaining open questions across the system architecture phase.

## Resolved Questions

### From ADR-006: System Architecture

**Q1: Import resolution heuristics** — Resolved in ADR-008. Six languages receive dedicated
tree-sitter configs with per-language import resolution heuristics in v1: Python,
JavaScript/TypeScript, Rust, Go, Java, C/C++. All other languages use the LLM extraction
path, which resolves imports directly against the file manifest.

**Q2: Project State migration** — Resolved in ADR-011. Simple version number in
`.docai/version`. On mismatch, warn user and regenerate. No migration scripts.

**Q3: LLM client abstraction** — Resolved in ADR-010. Thin wrapper around the call
interface. v1 implements Google GenAI SDK. Provider switching is a contained change
(new wrapper implementation).

**Q4: Parallelism** — Resolved in ADR-009. Bucket-based concurrency via asyncio is a v1
feature. Files within a bucket are processed concurrently. `max_concurrent_calls` setting
prevents rate limiting. Pipeline stages remain sequential for v1.

**Q5: Output directory structure** — Resolved in ADR-012. Default `.docai/docs/`,
configurable via `[output] directory` in `docai.toml` or `--output-dir` CLI flag.

### From ADR-007: File Discovery

**Q1: `.docaiignore` explicit type annotations** — Deferred to post-v1. The bare `!` form
with LLM identification is sufficient for v1. The `!file.xyz:python` syntax can be added
based on user feedback without changing the architecture.

**Q2: Symlink handling** — **Decided: ignore symlinks, warn if detected.** Symlinks are
skipped during directory traversal. If a symlink is encountered, a warning is emitted
listing the skipped symlink path and its target. This avoids infinite loop risks from
symlink cycles and duplicate processing. Users who need symlinked files documented can
use `.docaiignore` `!` patterns to force-include the actual target files.

**Q3: Large project walk performance** — Deferred. The walk with content hashing is
fast enough for typical projects. Optimize if profiling on real monorepos shows a
bottleneck. Potential optimizations include parallel hashing and incremental directory
scanning, but these are not v1 concerns.

### From ADR-008: Structure Extractor

**Q1: LLM output format** — **Decided: JSON with structured output and validation.**
All LLM calls that return structured data (entity extraction, import resolution, Pass 1
purposes) use JSON as the response format. The Google GenAI SDK's structured output setting
constrains the model to produce valid JSON matching a defined schema. A validator checks
semantic completeness (all expected entities present, all required fields populated, valid
entity categories, dependency paths exist in manifest). Validation failures trigger a
correction call: the validation errors are sent back to the LLM with the original prompt,
and the LLM returns corrected JSON. Maximum 3 validation retries before marking the file
as failed.

This approach applies uniformly across all LLM calls that produce structured data:
- Structure Extractor: entity extraction (LLM fallback path), entity verification (error path)
- Documentation Generator: Pass 1 purposes, per-file documentation, per-entity follow-ups,
  config file summaries, package summaries, Tier 2 invalidation comparison

**Q2: Config table extensibility** — **Decided: plugin architecture from v1.** Language
configs are loadable from external files/packages, not hardcoded into the main codebase.
Each language config is a self-contained definition (entity mapping table, import pattern
table, resolution heuristics, visibility rules) stored as a structured file (TOML or JSON).
v1 ships with six built-in configs (Python, JS/TS, Rust, Go, Java, C/C++) bundled with the
package. Third-party configs can be installed as separate packages and discovered by docai
at runtime (e.g., via entry points or a known config directory). This enables community
contributions without forking the main codebase. The plugin interface is the language config
schema — any file conforming to the schema is a valid language config.

**Q3: Entity extraction depth for nested structures** — **Decided: extract with parent
reference, stop at depth 2.** The extraction captures:
- Depth 0: top-level entities (functions, classes, constants, type aliases)
- Depth 1: entities nested inside depth-0 entities (methods inside classes, inner functions
  inside functions, enum variants)
- Depth 2: not extracted (nested classes inside classes, closures inside methods, etc.)

Depth-1 entities carry a `parent` field referencing the enclosing depth-0 entity name. This
covers the common and important case (class methods) without exploding the entity directory
for deeply nested structures. Depth-2+ entities are documented as part of their parent's
description, not as separate entities.

**Q4: Tree-sitter grammar installation** — Already resolved in ADR-008. Bundle all v1
grammars with the package.

### From ADR-009: Graph Builder

**Q1: Package summary threshold** — **Decided: 2+ documented files in a directory.**
Directories containing a single documented file do not get a separate package summary —
the file's own module-level documentation is sufficient. Directories with 2 or more
documented files get a `_package.md` summary explaining how the files work together. This
avoids generating redundant summaries for single-file directories while ensuring
multi-file directories get the organizational context.

**Q2: Monorepo support** — Deferred to future enhancement. v1 treats the entire project
root as a single dependency graph. Monorepo-aware features (detecting independent package
boundaries, treating subpackages as separate subgraphs) can be added later without changing
the core architecture.

**Q3: Bucket size limits** — Resolved in ADR-010. The `max_concurrent_calls` setting
(default: 5, configurable) limits how many LLM calls from a bucket run simultaneously.
The bucket model defines what *can* run concurrently; the concurrency limit controls how
many *do* run concurrently. This is enforced by the Documentation Generator using an
asyncio semaphore, not by the Graph Builder splitting buckets.

### From ADR-010: Documentation Generator

**Q1: Pass 1 batching threshold** — Resolved in ADR-011. File + directory count threshold
(configurable, default ~50-80 items). Split by top-level subdirectories when exceeded,
with sibling directories visible as names only. Recursive splitting if a single
subdirectory exceeds the threshold.

**Q2: Completeness verification parsing** — **Decided: JSON structured output with
validation.** All documentation generation calls return structured JSON, not freeform
markdown. The JSON schema defines fields for the module overview and per-entity
documentation keyed by entity name. The validator checks that all entities from the
FileAnalysis appear as keys in the response. Missing entities or empty fields trigger a
correction call with specific error messages. The final markdown documentation is assembled
programmatically from the validated JSON — YAML frontmatter from FileAnalysis/manifest data,
prose sections from LLM JSON responses, markdown formatting from templates. This eliminates
the need to parse prose output entirely.

**Q3: Cost tracking and reporting** — **Decided: track comprehensively, display
progressively.**

Three levels of cost information:

*Confirmation prompt* — shows estimated LLM call count as a range (minimum to ~120-125%
of minimum), giving users a quick sense of scope before committing.

*Post-run summary* — shows actual totals: LLM calls made, total input + output tokens
consumed, and estimated monetary cost if per-token pricing is configured in `docai.toml`:
```toml
[llm]
input_token_cost = 0.00015    # cost per 1K input tokens (optional)
output_token_cost = 0.0006    # cost per 1K output tokens (optional)
```
If pricing is not configured, the summary shows token counts only.

*Detailed run log* — written to `.docai/logs/` for benchmarking. Per-call metrics:
timestamp, file being processed, call type (pass1, per_file, per_entity, validation_retry,
comparison, config_summary, package_summary), input tokens, output tokens, latency in
milliseconds, success/failure. This enables analysis of where time and money are spent
across runs.

**Q4: Retry strategy** — **Decided: two-tier retry with configurable limits.**

*Connection retries* — for transient network/API errors (timeouts, rate limits, 5xx
responses): 3 retries with exponential backoff (configurable via `[llm] connection_retries`
in `docai.toml`). The set of retryable error types is configurable.

*Validation retries* — for LLM responses that fail schema or completeness validation: 3
retries where each retry sends the validation errors back to the LLM with the original
prompt (configurable via `[llm] validation_retries`). After exhausting retries, the file
is marked as `error` status in Project State and reported in the run summary. The next run
retries automatically.

Connection retries and validation retries are independent — a single call might experience
both (connection retry to get a response, then validation retry if the response is invalid).

**Q5: Package summary threshold** — Same as ADR-009 Q1. 2+ documented files.

### From ADR-011: Project State

**Q1: State directory location** — **Decided: `.docai/` always in project root for v1.**
No configurable location. The state directory is discovered by walking up from the current
working directory looking for `docai.toml` (which marks the project root). `.docai/` is
always a sibling of `docai.toml`. This simplifies discovery and avoids the "where did I
put my state?" problem. Configurable location can be added in a future version if users
need it.

**Q2: Garbage collection** — Resolved in ADR-012. Orphan cleanup runs automatically at the
start of each pipeline run: compare current manifest against stored state, remove state and
documentation files for source files that no longer exist. Additionally, `docai clean`
removes the entire `.docai/` directory for a full reset.

**Q3: Concurrent access protection** — **Decided: lockfile with PID.** On startup, docai
creates `.docai/lock` containing the current process ID. Before starting work, it checks
for an existing lockfile: if one exists and the PID is still a running process, docai exits
with an error ("another docai process is running, PID: XXXX"). If the PID is no longer
running (stale lockfile from a crash), the lockfile is removed and replaced. The lockfile
is removed on normal exit. `.docai/lock` should be added to `.gitignore` (it's
machine-specific, unlike the rest of `.docai/`).

**Q4: Pass 1 purpose staleness** — **Decided: re-run Pass 1 for changed files during
incremental regeneration.** When files change, their purpose sentences are regenerated
alongside the other incremental work. This is a cheap LLM call (one sentence per file)
and ensures the purpose sentences used in context assembly are accurate. The prompt for
incremental Pass 1 differs from the batch orientation sweep: it provides the existing
purposes for unchanged files as context and asks for updated purposes for the changed
files only.

### From ADR-012: CLI / Orchestrator

**Q1: CLI framework** — **Decided: argparse.** Standard library, no additional dependency,
sufficient for docai's straightforward command structure (5-6 subcommands, handful of
flags). The CLI is not complex enough to justify a framework dependency. `rich` handles
the output formatting and progress reporting side.

**Q2: API key management** — **Decided: environment variable as primary, config file as
secondary.** Priority order: environment variable (`GOOGLE_API_KEY` or provider-specific
equivalent) → `docai.toml` `[llm] api_key` field → prompt the user.

The config file option exists for convenience but carries a security warning. When
`docai init` creates the config file, the `api_key` field is commented out with a warning:
```toml
[llm]
# api_key = "..."  # WARNING: prefer environment variable to avoid committing secrets
```

If docai detects an API key in the committed config file, it warns the user to switch to
environment variables. The `.docai/lock` file is the only file in `.docai/` that should be
gitignored; the API key concern applies to `docai.toml` in the project root.

**Q3: Cost estimation display** — **Decided: show a range.** The confirmation prompt
displays estimated LLM calls as a range: "[minimum] - [minimum × 1.2]" where the minimum
is the known call count (Pass 1 + one per work item) and the upper bound adds ~20% for
per-entity follow-ups and validation retries. Example: "Estimated LLM calls: 145-175".

**Q4: Parallel Discovery and Extraction** — Deferred to post-v1. Pipeline stages remain
sequential for v1 (Discovery completes before Extraction begins). Streaming from Discovery
to Extraction is a natural asyncio optimization but adds pipeline complexity that isn't
justified until performance profiling on large projects indicates it's needed.

## Consequences

### Positive
- All open questions from the system architecture phase are resolved, providing a complete
  and implementable specification
- JSON structured output with validation eliminates the fragile prose-parsing problem and
  ensures consistent, complete documentation output
- Plugin architecture for language configs enables community contributions from v1 without
  requiring core codebase changes
- Comprehensive cost tracking with three display tiers (confirmation, summary, detailed log)
  supports both casual use and systematic benchmarking
- Two-tier retry strategy (connection + validation) maximizes recovery from transient failures
  while providing clear error feedback to the LLM for content issues
- Decisions consistently favor simplicity for v1 with clear extension paths (symlink support,
  monorepo awareness, streaming pipeline, configurable state location)

### Deferred Items
The following items are explicitly deferred to post-v1:
- `.docaiignore` explicit type annotations (`!file.xyz:python`)
- Large project walk performance optimization
- Monorepo support (independent subgraph detection)
- Streaming Discovery → Extraction pipeline
- Configurable state directory location

These are noted as future enhancements and do not block v1 implementation.
