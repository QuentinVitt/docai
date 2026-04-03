# ADR-011: Project State Component Design

## Status
Accepted

## Context
ADR-006 established Project State as a cross-cutting persistence layer — responsible for
storing and retrieving all intermediate and final artifacts produced by the pipeline. ADR-006
decided on a `.docai/` directory structure with per-file atomic updates. This ADR defines the
concrete design: what is stored, how it's organized on disk, how crash recovery works, how
incremental regeneration determines what to re-process, and how cache invalidation cascades
through dependencies.

### Key design considerations

- **Crash recovery**: LLM calls are expensive in time and money. If the pipeline crashes
  mid-run, the next invocation must resume from where it left off without re-doing completed
  work.
- **Incremental regeneration**: When a user changes a few files in a large project, only
  the affected files and their dependents should be re-processed. This requires tracking
  content hashes, dependency relationships, and generation status.
- **Cache invalidation depth**: A changed file may affect its dependents' documentation even
  if the dependents' source code hasn't changed. The invalidation strategy must be precise
  enough to maintain documentation consistency without unnecessarily regenerating unaffected
  files.
- **Atomicity**: Disk writes must survive crashes without corrupting previously valid state.

## Options Considered

### Storage organization

#### Option A: One bundled file per source file
All data related to a source file (FileAnalysis, generation status, content hash, Pass 1
purpose) stored in a single JSON file.
- **Pros**: One file to read/write per source file. Simple mapping.
- **Cons**: Loading just the generation status requires reading the entire bundle. Updating
  one field rewrites everything. A crash during write corrupts all data for that file.

#### Option B: Separate files per data type, mirroring source tree
Each pipeline stage writes its own output file for each source file: `analyses/src/parser.py.json`,
`docs/src/parser.py.md`, `status/src/parser.py.json`. Project-wide data lives in top-level
files.
- **Pros**: Load only what you need. A crash during documentation generation only risks the
  docs file, not the FileAnalysis. Each pipeline stage writes to its own namespace. Easier
  to inspect and debug — want to see all FileAnalysis results? Look in `analyses/`.
- **Cons**: More files on disk. More directory management logic. Multiple files to clean up
  when a source file is removed.

### Invalidation strategy

#### Option A: Content hash only — regenerate changed files, ignore dependents
- **Pros**: Simplest possible invalidation
- **Cons**: Dependents' documentation becomes stale when a dependency's interface changes.
  Inconsistent documentation across the project.

#### Option B: Always cascade to direct dependents
- **Pros**: Simple, always correct. No judgment about whether the change matters.
- **Cons**: Expensive for frequently-changed utility files that many files depend on.
  Internal-only changes (refactored implementation, same interface) trigger unnecessary
  regeneration of all dependents.

#### Option C: Two-tier invalidation — free pre-filter + cheap LLM comparison
- **Pros**: Obvious interface changes (new entities, changed signatures) cascade immediately
  without an LLM call. Subtle semantic changes (same interface, different behavior) are
  evaluated by a cheap LLM comparison call. Internal-only changes that don't affect
  documented behavior skip cascading entirely.
- **Cons**: The LLM comparison call adds cost for ambiguous cases. The LLM's judgment of
  "did behavior change meaningfully" is imperfect. More complex than always-cascade.

### State versioning

#### Option A: Versioned schemas with migration scripts
- **Pros**: Preserves cached state across docai version upgrades
- **Cons**: Migration logic is complex and error-prone. For a solo developer project, the
  maintenance burden of keeping migration scripts correct is not worth the saved regeneration
  cost.

#### Option B: Version number, regenerate on mismatch
- **Pros**: Simple, always correct. One full regeneration when upgrading docai is a minor
  cost compared to the complexity of maintaining migrations.
- **Cons**: Users pay for a full regeneration on every docai version upgrade that changes
  the state format.

## Decision

### Storage organization

**Separate files per data type, mirroring source tree** (Option B). The `.docai/` directory
contains:

```
.docai/
  version                              # state format version string
  manifest.json                        # project file list with classifications,
                                       #   content hashes, languages, file sizes,
                                       #   detection methods
  purposes.json                        # Pass 1 file + directory purpose sentences
  graph.json                           # dependency graph + processing plan (buckets)
  analyses/                            # FileAnalysis per source file
    src/
      parser.py.json                   # entities, dependencies, extraction method,
                                       #   parse errors for parser.py
      models.py.json
    tests/
      test_parser.py.json
  docs/                                # generated documentation per file
    src/
      parser.py.md                     # documentation for parser.py
      models.py.md
      _package.md                      # package summary for src/
    tests/
      test_parser.py.md
      _package.md
    Dockerfile.md                      # config file documentation
    _package.md                        # root-level package summary
  status/                              # generation status per file
    src/
      parser.py.json                   # { "state": "complete", "timestamp": "..." }
      models.py.json
    tests/
      test_parser.py.json
```

**Design rationale for this layout:**

- **`analyses/`** mirrors the source tree. Each file contains the FileAnalysis output from
  the Structure Extractor: entity directory, resolved dependencies, extraction method, parse
  error flag. Written once during structure extraction, read during documentation generation
  for context assembly.

- **`docs/`** mirrors the source tree. Contains the generated markdown documentation — this
  is both the final output and a dependency context source for other files' documentation.
  Package summaries use the `_package.md` convention within each directory.

- **`status/`** mirrors the source tree. Tracks per-file generation state: `not_started`,
  `extraction_complete`, `documentation_in_progress`, `complete`, `error`. This is the
  primary mechanism for crash recovery — on resume, files with `complete` status and matching
  content hashes are skipped.

- **`manifest.json`** is the project-wide file listing with content hashes, classifications,
  and detection metadata. Written by Discovery, read by all downstream components. Content
  hashes live here (not per-file) for fast comparison: load one file, diff all hashes at
  once.

- **`purposes.json`** contains all Pass 1 file and directory purpose sentences. Project-wide
  because Pass 1 is a project-wide operation. Written once during the orientation sweep, read
  during context assembly for every file.

- **`graph.json`** contains the dependency graph and the computed ProcessingPlan (bucket
  assignments). Written by the Graph Builder, read by the Documentation Generator for
  execution ordering.

### Atomic writes

All disk writes use **write-to-temp-then-rename**. A helper function writes data to
`<path>.tmp`, flushes to disk, then atomically renames to `<path>`. This guarantees that
the target file is either the old version or the new version, never a partial write.

On startup, the Project State component scans for any leftover `.tmp` files and removes
them — these are artifacts of interrupted writes and should be discarded.

### Crash recovery flow

When the pipeline is invoked and a `.docai/` directory already exists:

1. **Clean up**: Remove any `.tmp` files (interrupted writes from a previous crash)
2. **Load manifest**: Read `manifest.json`, compare stored content hashes against current
   file system (via new Discovery run)
3. **Identify work**:
   - Files with matching hashes and `complete` status → skip entirely
   - Files with matching hashes and `extraction_complete` status → skip extraction, resume
     at documentation generation
   - Files with matching hashes and `documentation_in_progress` status → restart documentation
     generation for this file (the in-progress output may be incomplete)
   - Files with changed hashes → full re-processing (extraction + documentation)
   - New files (in current file system but not in stored manifest) → full processing
   - Deleted files (in stored manifest but not in current file system) → remove their state
     files, update graph
4. **Re-run affected pipeline stages**: Discovery (always, to get current file list and
   hashes), Structure Extraction (for changed/new files), Graph Building (if any dependencies
   changed), Pass 1 (for changed/new files — existing purposes for unchanged files are
   preserved), Documentation Generation (for changed files + invalidated dependents per
   cascade rules)

### Incremental regeneration and cache invalidation

When source files change between runs, the invalidation strategy determines which files
need re-documentation. This uses a **two-tier approach** — a free pre-filter for obvious
changes, with a cheap LLM comparison call for ambiguous cases.

#### Tier 1: Entity directory diff (free, no LLM)

After re-running the Structure Extractor on a changed file, compare the new FileAnalysis
against the stored FileAnalysis:

**Check for:**
- Added or removed entities
- Changed entity signatures (parameter types, return types)
- Changed entity visibility (public ↔ private)
- Changed entity categories
- Changed dependency list (new imports, removed imports)

**If any of these changed** → the file's interface has changed. This is an obvious case:
- Re-document the changed file
- Cascade: re-document all files that directly import from this file
- Regenerate package summaries for all directories in the changed file's path up to the
  project root

**If none of these changed** → the file's interface is stable but implementation changed.
Proceed to Tier 2.

#### Tier 2: LLM comparison (cheap, targeted)

The entity directory looks the same but the source code changed. The change might be purely
internal (refactored implementation, performance improvement) or it might be a semantic change
that affects how callers should understand the function (switched from database to API,
changed error behavior, different side effects).

**LLM comparison call receives:**
- Old generated documentation for the file
- New generated documentation for the file (just produced by re-documenting the changed file)

**Focused question:** "Did the documented behavior of any public entity change in a way that
would affect how other files that call or reference these entities understand or use them?"

**Output:** Yes/no with a list of entities whose documented behavior changed meaningfully.

**If yes** → cascade to direct dependents + regenerate directory summaries.
**If no** → no cascade needed. Only regenerate directory summaries (the module overview may
have changed even for internal changes, and directory summaries are cheap).

This two-tier approach means:
- Obvious interface changes cascade immediately with zero LLM cost
- Ambiguous semantic changes get a cheap, focused LLM judgment call
- Pure internal refactors (most common case for mature codebases) avoid unnecessary
  regeneration of dependents entirely

#### Directory summary regeneration

Package summaries (directory-level documentation) are regenerated whenever any constituent
file's documentation changes, regardless of whether dependents cascade. Directory summaries
are cheap (short LLM call based on file-level overviews) and should always reflect the
current state of their constituent files.

Regeneration propagates up the directory tree: if `src/parsing/tokenizer.py` changes,
regenerate `src/parsing/_package.md`, then `src/_package.md`, then the root `_package.md`.

### Pass 1 batching for large projects

When the project is too large for a single Pass 1 orientation sweep call, split by
directory using a **file + directory count threshold** (configurable, default ~50-80 items).

**Split algorithm:**
1. Count total files + directories in the project
2. If under threshold → single Pass 1 call with everything
3. If over threshold → split by top-level directories. Each gets its own Pass 1 call.
4. Each call receives:
   - Project description
   - Top-level directory listing (names only, no children) for project-wide orientation
   - Full subtree of its assigned directory with entity directories for all files within
5. If a single top-level directory exceeds the threshold, recursively split by its children
6. For directories already processed by earlier calls in the batch, substitute the generated
   purpose sentence for the full subtree (the LLM sees "parsing/: handles converting raw
   source into structured representations" instead of the full listing)

This keeps each call's output item count manageable, ensuring quality descriptions for
every file and directory.

### State versioning

**Version number in `.docai/version`, regenerate on mismatch** (Option B). The version file
contains a simple version string (e.g., `"1"` or `"2"`). On startup, if the stored version
doesn't match the expected version for the current docai release, the user is warned and
offered the choice to regenerate all documentation. No migration logic.

The version number only changes when the state format changes in an incompatible way. Bug
fixes, prompt improvements, and new features that don't change the stored data format do not
require version bumps.

## Consequences

### Positive
- Separate files per data type enable loading only what's needed and isolate crash damage
  to the specific stage that was interrupted
- Write-to-temp-then-rename prevents corruption from mid-write crashes at negligible
  implementation cost
- Two-tier invalidation balances precision with cost: obvious changes cascade for free,
  ambiguous changes get a cheap LLM judgment, pure internal changes avoid unnecessary work
- Entity directory diff as the pre-filter is deterministic, fast, and directly measures
  what dependents care about (the file's interface)
- Status tracking per file enables fine-grained resume — the pipeline picks up exactly
  where it left off
- Simple version number with regeneration avoids migration complexity while ensuring state
  format compatibility
- Hierarchical Pass 1 batching scales to large projects without degrading output quality

### Negative / Trade-offs accepted
- Separate files per data type means more filesystem operations and directory management.
  Acceptable for the isolation and debugging benefits.
- The LLM comparison call in Tier 2 invalidation adds cost for ambiguous changes. This is
  bounded (one cheap call per changed file that passes Tier 1) and cheaper than always
  cascading to dependents.
- The LLM's judgment of "did behavior change meaningfully" in Tier 2 is imperfect — it may
  occasionally miss a semantic change that should cascade, or flag an unimportant change for
  cascading. In practice, this is better than either extreme (never cascade or always cascade).
- Regenerate-on-version-mismatch means users pay for a full regeneration on docai upgrades
  that change the state format. This is infrequent and simpler than maintaining migrations.
- Deleting a source file requires cleaning up multiple state files across `analyses/`,
  `docs/`, and `status/`. A cleanup helper function handles this.

### Constraints created
- Need to define JSON schemas for: manifest.json, FileAnalysis files, status files,
  purposes.json, graph.json
- Need to implement the atomic write helper and `.tmp` file cleanup on startup
- Need to implement the entity directory diff logic for Tier 1 invalidation
- Need to design the Tier 2 LLM comparison prompt
- Need to implement the directory tree mirroring logic (creating/removing subdirectories
  in `analyses/`, `docs/`, `status/` as source files are added/removed)
- The Documentation Generator must update status files at each stage transition
  (extraction_complete → documentation_in_progress → complete)

## Open Questions

1. **State directory location**: Should `.docai/` always be in the project root, or should
   it be configurable? A user might want state stored outside the project directory (e.g.,
   in `~/.cache/docai/`). Configurable location adds flexibility but complicates discovery
   on subsequent runs.

2. **Garbage collection**: Over time, as source files are renamed or deleted, orphaned state
   files accumulate. Should there be an explicit cleanup command (`docai clean`), or should
   the pipeline automatically remove state files for source files that no longer exist?

3. **Concurrent access**: If two docai processes run simultaneously on the same project
   (unlikely but possible), the state directory could be corrupted. Should there be a
   lockfile mechanism? A simple `.docai/lock` file with PID would prevent concurrent runs.

4. **Pass 1 purpose staleness**: When a file changes, its Pass 1 purpose sentence may be
   stale. Should Pass 1 be re-run for changed files during incremental regeneration, or
   is the old purpose sentence good enough? Re-running Pass 1 for individual files is cheap
   but requires a different prompt than the batch orientation sweep.
