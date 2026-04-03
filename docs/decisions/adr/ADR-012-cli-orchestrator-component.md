# ADR-012: CLI / Orchestrator Component Design

## Status
Accepted

## Context
ADR-006 established the CLI/Orchestrator as the sixth and outermost pipeline component —
responsible for user interaction, configuration management, pipeline coordination, and
progress reporting. All other components (Discovery, Structure Extractor, Graph Builder,
Documentation Generator, Project State) have been designed in ADRs 007-011. This ADR defines
how the user interacts with docai and how the pipeline stages are coordinated.

### Key design considerations

- **First-run friction**: The first run should be as simple as possible — ideally one command
  with minimal configuration. But it should also be transparent about what it's about to do
  (file count, estimated cost) before making expensive LLM calls.
- **Incremental UX**: Subsequent runs should be fast and automatic — detect changes, process
  only what's needed, report what was done.
- **Team sharing**: The `.docai/` directory and generated documentation should be
  git-committable so team members benefit without regenerating.
- **Path handling**: All stored paths must be relative to the project root for portability
  across machines and directory locations.

## Decision

### Command interface

| Command | Description |
|---------|-------------|
| `docai` | Default action: if no `docai.toml` exists, runs init flow then generate. If config exists, runs generate (incremental if state exists). |
| `docai init` | Set up project configuration: create `docai.toml`, prompt for project description, run Discovery to preview what would be documented. Does not generate documentation. |
| `docai generate` | Run the documentation pipeline. Incremental if `.docai/` state exists, full run otherwise. |
| `docai generate --force` | Ignore all cached state, regenerate everything from scratch. |
| `docai generate <path>` | Document a specific file or directory only. Runs Discovery and Structure Extraction for the target, assembles context using raw source for any unprocessed dependencies, generates documentation for the target only. |
| `docai status` | Show documentation state: what's documented, what's stale, what's unknown, what's pending. |
| `docai list` | Show the file manifest: all discovered files with their classifications, languages, and detection methods. Useful for debugging Discovery and `.docaiignore` rules. |
| `docai clean` | Remove the `.docai/` state directory entirely. Does not remove `docai.toml` (user config) or documentation if the output directory is outside `.docai/`. |

**Global flags:**

| Flag | Description |
|------|-------------|
| `--description "..."` | Override project description for this run |
| `--output-dir <path>` | Override output directory for this run |
| `--model <name>` | Override LLM model for this run |
| `--yes` / `-y` | Skip confirmation prompts (for CI/scripted usage) |
| `--verbose` / `-v` | Show per-file detail during processing |
| `--quiet` / `-q` | Show only warnings, errors, and final summary |

### Configuration

**Location**: `docai.toml` in the project root (not inside `.docai/`). This file is
user-edited configuration that should be committed to version control. The `.docai/`
directory is generated state.

**Format**: TOML (Python ecosystem standard, `tomllib` in stdlib since 3.11).

**Precedence**: CLI flags → `docai.toml` → built-in defaults.

**Schema**:

```toml
[project]
description = "CLI tool that generates documentation for code using LLMs"

[generation]
per_entity_threshold = 15        # entity count triggering per-entity follow-ups
max_concurrent_calls = 5         # max concurrent LLM calls per bucket
context_warning_tokens = 80000   # warn when assembled context exceeds this

[llm]
provider = "google-genai"        # LLM provider (google-genai for v1)
model = "gemini-2.0-flash"       # model identifier

[output]
directory = ".docai/docs"        # documentation output directory (relative to project root)

[discovery]
ignore = []                      # additional ignore patterns (supplements .docaiignore)
```

Only `[project] description` is required. All other settings have sensible defaults.

### Project description handling

The project description is sourced from (in priority order):

1. CLI flag: `--description "..."`
2. Config file: `[project] description` in `docai.toml`
3. Auto-detection: check known project metadata files (`pyproject.toml` `[project] description`,
   `package.json` `description`, `Cargo.toml` `[package] description`) and suggest if found
4. Interactive prompt: ask the user during `docai init` or first run

During `docai init`, if a description is found in project metadata:
```
Found project description in pyproject.toml:
  "A CLI tool for automated code documentation"
Use this? [Y/n/custom]
```

The accepted or entered description is saved to `docai.toml` automatically. Subsequent runs
use it without prompting.

### Path handling

**All paths stored in `.docai/` state files are relative to the project root.** This is a
design invariant enforced across all components:

- File manifest entries: relative paths
- FileAnalysis file paths and dependency references: relative paths
- Dependency graph nodes: relative paths
- Documentation file paths: relative paths
- Configuration paths (output directory, ignore patterns): relative to project root

The project root is determined at runtime: the directory containing `docai.toml`, or the
current working directory if no config exists. Absolute paths are constructed only at I/O
boundaries: `project_root / relative_path` when reading or writing files. Never stored.

This ensures the `.docai/` directory and all cached state remain valid when the project is
moved, cloned to another machine, or checked out at a different path.

### `.docai/` as a git-committable artifact

The `.docai/` directory is designed to be committed to version control. It contains:

- Generated documentation (the primary deliverable — team members want to read this)
- Cached analysis results (FileAnalysis, dependency graph, file purposes)
- Content hashes and generation status

When a team member clones the repository and runs `docai`, the pipeline:
1. Runs Discovery, computes current content hashes
2. Compares against stored hashes in `manifest.json`
3. Finds everything matches → skips all processing
4. Finishes instantly

If they've made local changes, only changed files and their dependents are re-processed.

The `.docaiignore` file should include `.docai/` (so docai doesn't try to document its own
state directory). But `.gitignore` should **not** include `.docai/` — it's meant to be shared.

**Exception**: `.tmp` files (artifacts of interrupted writes) should be in `.gitignore`:
```
# .gitignore
.docai/**/*.tmp
```

### Pipeline orchestration

The orchestrator coordinates all pipeline stages. The flow differs for full runs vs.
incremental runs:

#### Full run (no existing state)

```
1. Discovery
   → File manifest (classifications, hashes, languages)
   → Save to Project State

2. Structure Extraction (all source files, concurrent per file)
   → FileAnalysis per file
   → Save each to Project State as completed

3. Graph Building
   → Dependency graph + ProcessingPlan (buckets)
   → Save to Project State

4. Pass 1: Orientation Sweep
   → File + directory purpose sentences
   → Batched by directory if project exceeds item count threshold
   → Save to Project State

5. Pass 2: Detailed Documentation (bucket by bucket)
   → For each bucket: process all items concurrently (up to max_concurrent_calls)
   → For source files: per-file documentation, with per-entity follow-ups if threshold exceeded
   → For config files: module-level summary
   → For package summaries: directory-level rollup
   → Save each completed doc to Project State, update status
   → Completeness verification after each source file

6. Orphan cleanup
   → Remove documentation files for source files no longer in manifest

7. Done
   → Report summary
```

#### Incremental run (existing state)

```
1. Discovery
   → New file manifest with current hashes

2. Diff against stored manifest
   → Changed files: content hash differs
   → New files: in current manifest but not stored
   → Deleted files: in stored manifest but not current
   → Unchanged files: hash matches, status complete → skip

3. Structure Extraction (changed + new files only)
   → New FileAnalysis per file

4. Invalidation assessment (per changed file)
   → Tier 1: Entity directory diff (free)
     - Signatures, entities, dependencies changed? → cascade
     - Only implementation changed? → Tier 2
   → Tier 2: LLM comparison (cheap)
     - Re-document changed file first
     - Compare old docs vs new docs
     - Semantic change detected? → cascade to direct dependents
     - No semantic change? → no cascade

5. Graph Building (if any dependency lists changed)
   → Rebuild graph with updated FileAnalysis data
   → Recompute ProcessingPlan

6. Pass 1 (for changed/new files only)
   → Update purpose sentences for affected files
   → Preserve existing purposes for unchanged files

7. Pass 2 (for changed files + cascaded dependents + affected package summaries)
   → Same bucket-based concurrent execution
   → Only process files identified by invalidation

8. Orphan cleanup
   → Remove state and docs for deleted files

9. Done
   → Report summary (X files updated, Y skipped, Z new)
```

### Unprocessed dependency handling

When a documented file has a dependency that exists but hasn't been processed (because it's
ignored via `.docaiignore`, classified as unknown, or not yet processed in a partial run),
the context assembly uses the **raw source code** of the dependency file.

The fallback chain for dependency context:
1. Generated documentation exists → use it (best case)
2. FileAnalysis exists but no docs → use entity directory + raw source
3. File exists but no FileAnalysis → use raw source only
4. File doesn't exist (external/third-party) → no context, LLM uses training knowledge

This ensures documentation quality degrades gracefully rather than failing when dependencies
are unavailable.

### Progress reporting

**Implementation**: `rich` library for terminal UI — progress bars, styled output, tables
for status commands.

**Primary metric**: LLM calls remaining. A progress bar shows completed/total LLM calls
across the entire run. The total is computed from the ProcessingPlan:
- Pass 1 calls (1 or more depending on batching)
- Pass 2 per-file/config/package calls (one per work item)
- Estimated per-entity follow-ups are added to the total dynamically as they're determined
  (the progress bar total updates mid-run when a large file triggers follow-ups)

**Verbosity levels:**

**Default** — stage transitions + progress bar:
```
Discovering files... 147 found (132 source, 8 config, 7 ignored)
Extracting structure... 132/132
Building dependency graph... 132 nodes, 284 edges
Generating documentation ━━━━━━━━━━━━━━━━━━━━━━ 67/145 calls
Complete: 140 files documented → .docai/docs/
```

**Verbose** (`-v`) — adds per-file detail:
```
Extracting structure...
  src/parser.py [tree-sitter] ✓
  src/models.py [tree-sitter] ✓
  src/utils.py [tree-sitter, parse errors → llm-verified] ✓
  scripts/deploy.sh [llm-fallback] ✓
```

**Quiet** (`-q`) — warnings, errors, and final summary only.

**Warnings are always shown** regardless of verbosity:
- Unknown files skipped
- Parse errors detected
- Large context warnings
- LLM call failures

### First-run experience

When `docai` is run with no existing `docai.toml`:

```
$ docai

No docai configuration found. Setting up...

Describe your project in one sentence
(found in pyproject.toml: "A CLI documentation generator"):
> [enter to accept, or type custom description]

Saved to docai.toml

Discovering files... 147 found (132 source, 8 config, 7 ignored, 3 unknown)

⚠ 3 files with unrecognized types were skipped:
  data/schema.prisma
  scripts/setup.zx
  config/rules.rego
  (Add to .docaiignore with ! prefix to force-include)

Ready to generate documentation for 140 files.
Estimated LLM calls: ~145
Proceed? [Y/n]
```

**Confirmation prompt behavior:**
- First run: always confirm (the user hasn't seen what docai will do yet)
- Incremental run with small change set (< 20 files affected): no confirmation, just run
- Incremental run with large change set (≥ 20 files affected): confirm with summary
- `--yes` flag: skip all confirmations (CI/scripted usage)
- `docai generate --force`: confirm (full regeneration is expensive)

The threshold for "large change set" (20 files) is a sensible default, not configurable in
v1. Can be made configurable based on user feedback.

### Output directory management

**Default output directory**: `.docai/docs/` (configurable via `[output] directory` in
config or `--output-dir` flag).

**Write strategy**: Overwrite only. Files are written or updated in place. Existing
documentation files for unchanged source files are left untouched.

**Orphan cleanup**: At the start of each run (after Discovery), compare the current file
manifest against existing documentation files. Remove documentation files that correspond
to source files no longer in the manifest. This handles deleted and renamed files cleanly.

**`docai clean`**: Removes the entire `.docai/` directory (state + default output). If the
output directory is configured outside `.docai/`, `docai clean` removes the `.docai/` state
directory only — the external output directory is left for the user to manage. A
`--include-output` flag could force removal of the external output directory as well.

### Error handling strategy

Errors are categorized by severity and recoverability:

**Recoverable errors** (logged, file skipped, pipeline continues):
- LLM call failure for a single file (after retries)
- Parse error in a source file (tree-sitter continues with error recovery)
- Import resolution failure for a single import (logged as warning)

**Pipeline errors** (reported, pipeline stops):
- LLM API authentication failure (no valid API key)
- File system permission errors (can't write to `.docai/`)
- Configuration errors (invalid `docai.toml`)

**Files that fail documentation** are marked with `error` status in Project State and
reported in the final summary. The next run retries them automatically (error status
doesn't prevent re-processing).

## Consequences

### Positive
- `docai init` separates configuration from generation — users can review and adjust before
  spending money on LLM calls
- Bare `docai` with no arguments does the right thing in all cases (init + generate on first
  run, incremental generate on subsequent runs)
- All paths stored as relative to project root ensures portability across machines and
  directory locations
- `.docai/` as a git-committable artifact means team members get documentation without
  regenerating
- Rich progress reporting with LLM calls remaining gives users clear feedback during
  long-running operations
- Graceful degradation for unprocessed dependencies (raw source fallback) means partial
  runs and ignored files don't break the pipeline
- Orphan cleanup handles deleted/renamed files without requiring a full directory wipe

### Negative / Trade-offs accepted
- `docai generate <path>` operates with reduced context (raw source for unprocessed
  dependencies). The resulting documentation may be less rich than a full run. Acceptable
  for a quick single-file preview.
- Auto-detection of project description from metadata files adds a small amount of
  complexity to the init flow. Worth it for the improved UX.
- Rich library is an additional dependency. Justified by the significant UX improvement
  for a CLI tool with long-running operations.
- The confirmation prompt adds friction to the first run. Necessary friction — the user
  should know what they're about to spend before LLM calls start.

### Constraints created
- Need to implement TOML config file parsing with validation and defaults
- Need to implement the `rich`-based progress reporting system with dynamic total updates
- Need to implement the orphan cleanup logic (manifest diff against docs directory)
- Need to implement the `docai generate <path>` scoped pipeline variant
- Need to define the exact CLI argument parsing (likely using `click` or `typer` for
  Python CLI tools)

## Open Questions

1. **CLI framework**: `click` vs `typer` vs `argparse`? `typer` builds on `click` and
   provides type-hint-based argument parsing, which fits Python idioms well. `click` is
   more established. `argparse` is stdlib but more verbose. Leaning toward `typer` for
   developer ergonomics.

2. **API key management**: Where does the LLM API key come from? Environment variable
   (`GOOGLE_API_KEY`)? Config file (security concern — config may be committed)? System
   keyring? Environment variable is the standard approach and avoids accidentally committing
   secrets. The config file should never store API keys.

3. **Cost estimation accuracy**: The "estimated LLM calls" shown in the confirmation prompt
   is approximate — it doesn't account for per-entity follow-ups (determined after per-file
   calls) or completeness verification retries. Should the estimate include a buffer, or
   just show the known minimum?

4. **Parallel Discovery and Extraction**: Could Structure Extraction start processing files
   as Discovery finds them (streaming), rather than waiting for Discovery to complete? This
   would reduce total wall time for large projects. Adds pipeline complexity but is a natural
   fit for asyncio.
