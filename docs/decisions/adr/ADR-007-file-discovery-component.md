# ADR-007: File Discovery Component Design

## Status
Accepted

## Context
ADR-006 established File Discovery as the first component in the pipeline — responsible for
walking the project directory, classifying files, and producing the file manifest that every
downstream component consumes. ADR-005 defined the high-level file classification rules
(source code, code-like config, ignored). This ADR defines the concrete design: how files
are detected, classified, and represented in the manifest.

### Key design considerations

- **Binary safety**: Binary files must be detected reliably before they enter the pipeline.
  A binary file reaching the Structure Extractor wastes an LLM call or produces garbage
  tree-sitter output.
- **Extensionless files**: Real projects contain important files with no extension (Dockerfile,
  Makefile, Jenkinsfile) and occasionally extensionless scripts with shebangs. These must be
  handled without requiring user configuration.
- **Unknown files**: Not every file can be automatically classified. The system must handle
  unknowns gracefully rather than guessing wrong and producing bad output downstream.
- **User control**: Every project has unique conventions. Users need the ability to override
  automatic classification in both directions (exclude files that would be included, include
  files that would be excluded).
- **Cost efficiency**: File discovery runs on every invocation. Detection methods must be cheap
  — no LLM calls during normal discovery. LLM identification is reserved for user-overridden
  unknown files only.

## Options Considered

### Unknown file handling

#### Option A: Default unknown files to source code
- **Pros**: Maximizes coverage, no user action needed
- **Cons**: Pushes unrecognized files through the full pipeline. Tree-sitter fails (no
  grammar), LLM fallback triggers, wasting an expensive call on files that may be binary,
  data, or otherwise nonsensical. Directly contradicts cost efficiency goals.

#### Option B: Warn and skip, with user override
- **Pros**: No wasted LLM calls. User is informed and can take action. Force-included unknowns
  go through LLM identification with validation against the known type registry. Conservative
  and predictable.
- **Cons**: Requires user action for genuinely novel file types. Slightly more friction on
  first run for unusual projects.

### Content-based detection scope

#### Option A: Binary detection only (magic bytes)
- **Pros**: Simple, reliable, solves the most dangerous misclassification
- **Cons**: Misses extensionless scripts that could be identified via shebang

#### Option B: Magic bytes + shebang + heuristic language detection
- **Pros**: Maximum automatic coverage
- **Cons**: Heuristic language detection (guessing Python vs. Ruby from content) is fragile,
  produces false positives, and adds complexity for marginal benefit

#### Option C: Magic bytes + shebang detection, nothing more
- **Pros**: Catches binaries (tier 1) and extensionless scripts (tier 2) reliably. Avoids
  unreliable content-based language guessing. Clear boundary: if detection isn't confident,
  the file is unknown.
- **Cons**: Won't auto-detect extensionless files without shebangs. Acceptable — these are
  rare and handled by the unknown file override flow.

### `.docaiignore` semantics

#### Option A: Exclusion only (additive on top of defaults)
- **Pros**: Simple, familiar, no rule interaction complexity
- **Cons**: Users cannot document files that the built-in defaults ignore. "I can't document
  this file I need" is a frustrating dead end.

#### Option B: Full `.gitignore` semantics with `!` negation
- **Pros**: Users can exclude and include. `!vendor/custom-lib/**` force-includes a vendored
  directory the defaults would skip. User intent is absolute. Familiar syntax for anyone
  who's used `.gitignore`.
- **Cons**: Negation adds rule processing complexity — rules apply in order, later rules
  override earlier ones. Interaction between built-in defaults and user rules needs clear
  definition.

## Decision

### File classification categories

Four categories (extending ADR-005's three with an explicit unknown state):

**1. Source code** — programming language files that enter the full documentation pipeline
(tree-sitter parsing, entity extraction, per-file narrative, per-entity reference).

**2. Code-like configuration** — files containing logic or structure that developers need to
understand (Dockerfiles, Makefiles, CI configs, SQL migrations, Terraform, docker-compose).
Documented at module-level depth only.

**3. Ignored** — files with no documentation value (binaries, generated directories, lockfiles,
tool boilerplate config, existing documentation).

**4. Unknown** — files that could not be automatically classified. Warned about, skipped from
processing, and available for user override.

### Detection stack

Files are classified through a layered detection stack. Each layer either classifies the file
or passes it to the next layer. The stack is ordered to catch dangerous misclassifications
early (binaries) and apply user overrides last (so user intent always wins).

```
1. Directory pruning (during walk)
   Built-in directory exclusions: .git/, node_modules/, __pycache__/, build/,
   dist/, target/, vendor/, .docai/
   .docaiignore directory patterns applied here
   → Prunes entire subtrees, never descends into them

2. Magic byte detection (first 4-8 bytes of file)
   Check against known binary signatures: ELF, PNG, JPEG, GIF, PDF, ZIP,
   Mach-O, PE, WASM, etc.
   → Binary detected → classify as ignored

3. Filename map (exact filename match)
   Dockerfile → dockerfile / config
   Makefile → make / config
   Justfile → just / config
   Jenkinsfile → groovy / config
   Rakefile → ruby / source
   Gemfile → ruby / config
   Procfile → procfile / config
   (and similar well-known extensionless filenames)
   → Match found → classify with language and category

4. Shebang detection (first line starts with #!)
   Parse interpreter from shebang line:
   #!/usr/bin/env python3 → python / source
   #!/bin/bash → bash / source (or config, depending on context)
   #!/usr/bin/env node → javascript / source
   → Shebang found with known interpreter → classify with language and category

5. Extension map (file extension lookup)
   .py → python / source
   .rs → rust / source
   .js → javascript / source
   .ts → typescript / source
   .go → go / source
   .java → java / source
   .c, .h → c / source
   .cpp, .hpp, .cc → cpp / source
   .rb → ruby / source
   .yml, .yaml → yaml / config
   .toml → toml / config
   .json → json / config (but not lockfiles — caught by filename)
   .sql → sql / config
   .tf → terraform / config
   .lock → ignored (lockfiles)
   (and other common extensions)
   → Match found → classify with language and category

6. .docaiignore file-level overrides
   Applied last, overrides any automatic classification.
   Exclusion patterns: remove files from processing
   ! negation patterns: force-include files that would be ignored or unknown
   → Force-included files with unknown type trigger LLM identification
     (see unknown file override flow below)

7. No match → classify as unknown
   File is included in manifest with classification "unknown"
   Warning emitted to user at end of discovery
   File is skipped during processing
```

### `.docaiignore` semantics

**Full `.gitignore` syntax with `!` negation** (Option B). Applied in two phases:

**Phase 1 — Directory pruning (during walk):** Directory-level patterns from both built-in
defaults and `.docaiignore` are applied during traversal. Matched directories are never
descended into. This is a performance optimization — `node_modules/` with 50,000 files is
never enumerated.

**Phase 2 — File-level overrides (after detection):** File-level patterns from `.docaiignore`
override automatic classification. Exclusion patterns remove files from processing. `!`
negation patterns force-include files, overriding both built-in ignores and automatic
detection.

Rules are processed in order. Later rules override earlier ones. Built-in defaults are
treated as if they appear before the user's `.docaiignore` rules, so user rules always win.

### Unknown file override flow

When a user force-includes an unknown file via `!` negation in `.docaiignore`:

1. File is marked as force-included in the manifest
2. During Structure Extraction, the LLM receives the file content and is asked to identify
   the language and whether it's source code or configuration
3. The LLM's response is validated against the known language/type registry
4. If the LLM returns a recognized type → proceed with that classification
5. If the LLM cannot identify the file or returns an unrecognized type → warn the user,
   suggest adding an explicit type annotation, skip the file

This ensures unknown types never silently enter the pipeline with an unrecognized language
that would confuse downstream components.

**Future enhancement**: Support explicit type annotation in `.docaiignore` to bypass LLM
identification entirely: `!weird-file.xyz:python` would force-include and classify as Python
source in one step. Not required for v1 — the bare `!` form with LLM identification is
sufficient.

### Manifest contents

The file manifest includes the following per file:

| Field | Description | Source |
|-------|-------------|--------|
| `relative_path` | Path relative to project root | Directory walk |
| `classification` | `source`, `config`, `ignored`, `unknown` | Detection stack |
| `language` | Detected language identifier (e.g., `python`, `rust`, `dockerfile`) or `null` for unknown/ignored | Detection stack |
| `content_hash` | Hash of file contents (SHA-256) | Computed during walk |
| `file_size_bytes` | File size in bytes | File stat during walk |
| `detection_method` | How classification was determined: `magic_bytes`, `filename`, `shebang`, `extension`, `docaiignore_override`, `default_unknown` | Detection stack |
| `force_included` | Boolean — whether file was force-included via `!` pattern | `.docaiignore` processing |

Content hashes are computed during the walk for all non-ignored files. This allows Project
State to immediately compare against the previous run's hashes without a second pass over
the file system.

File size is captured from the stat call already performed during the walk. This is consumed
downstream by the Documentation Generator for the large-file threshold (per-file vs.
per-entity documentation mode).

The `detection_method` field aids debugging — when a file is misclassified, the user (or a
future diagnostic command) can see which detection layer made the decision.

### Walk strategy

**Depth-first traversal with early directory pruning.** Directories matching built-in
exclusion patterns or `.docaiignore` directory patterns are skipped entirely during traversal
— no descent, no file enumeration. This is essential for performance on projects with large
generated directories.

The walk visits all remaining files, applies the detection stack (magic bytes → filename →
shebang → extension → `.docaiignore` overrides → unknown fallback), computes content hashes
for non-ignored files, and produces the complete manifest.

Ignored files are included in the manifest with their classification (for debugging and
completeness) but are not hashed and are excluded from all downstream processing.

### Built-in defaults

The following defaults are hardcoded in the source (not a separate config file). They can
all be overridden by `.docaiignore`.

**Ignored directories** (pruned during walk):
`.git/`, `node_modules/`, `__pycache__/`, `build/`, `dist/`, `target/`, `vendor/`,
`.docai/`, `.venv/`, `venv/`, `.tox/`, `.mypy_cache/`, `.pytest_cache/`, `.next/`,
`.nuxt/`, `coverage/`, `.eggs/`, `*.egg-info/`

**Ignored by extension**:
Lockfiles: `.lock` (with filename exceptions — `Cargo.lock`, `package-lock.json`,
`poetry.lock`, `yarn.lock` matched by full filename)
Binary extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.ico`, `.svg`, `.webp`,
`.mp3`, `.mp4`, `.wav`, `.avi`, `.mov`, `.pdf`, `.zip`, `.tar`, `.gz`, `.rar`, `.7z`,
`.exe`, `.dll`, `.so`, `.dylib`, `.o`, `.a`, `.pyc`, `.pyo`, `.class`, `.wasm`

**Ignored by filename**:
`.prettierrc`, `.eslintrc`, `.editorconfig`, `.gitignore`, `.gitattributes`,
`package-lock.json`, `Cargo.lock`, `poetry.lock`, `yarn.lock`, `pnpm-lock.yaml`

**Ignored — existing documentation**:
`README.md`, `README.rst`, `README.txt`, `CONTRIBUTING.md`, `CHANGELOG.md`,
`docs/` directory, and any previously generated `.docai/` output

## Consequences

### Positive
- Binary files are caught early via magic bytes, before they can waste LLM calls or produce
  garbage output downstream
- Extensionless files with shebangs (common in Unix scripts) are automatically detected
  without user configuration
- Unknown files are handled honestly — warned about and skipped rather than silently
  misclassified. User has a clear path to resolution via `.docaiignore` override.
- `.docaiignore` with `!` negation gives users complete control over classification, matching
  a familiar syntax
- Content hashes computed during walk eliminate the need for a second file system pass
- Detection method tracking aids debugging when classification is wrong
- Built-in defaults cover the common case — most projects need zero configuration
- LLM identification for force-included unknowns is validated against the type registry,
  preventing unrecognized types from entering the pipeline

### Negative / Trade-offs accepted
- Magic byte detection requires maintaining a list of binary signatures. In practice this
  is a solved problem — a small lookup table covers the vast majority of binary formats.
- `.docaiignore` with `!` negation adds rule processing complexity. Accepted because the
  alternative (users unable to document files they need) is worse.
- Hardcoded defaults will be wrong for some projects (e.g., a project that wants its `vendor/`
  directory documented). `.docaiignore` is the escape hatch.
- The unknown file override flow adds an LLM call during what is otherwise an LLM-free
  discovery phase. This only triggers for user-overridden files and is bounded by the number
  of force-included unknowns.
- Shebang detection only works for Unix-style scripts. Windows batch files and PowerShell
  scripts rely on extension detection (`.bat`, `.ps1`), which is fine in practice.

### Constraints created
- Need to define the complete extension-to-language map and filename-to-type map (can be
  expanded incrementally as languages are added)
- Need to define the magic byte signature table for binary detection
- Need to implement `.gitignore`-compatible pattern matching with `!` negation (existing
  Python libraries like `pathspec` may handle this)
- The manifest schema defined here becomes the input contract for the Structure Extractor
  and Project State — changes to it affect both downstream components

## Open Questions

1. **`.docaiignore` explicit type annotations**: Should v1 support `!file.xyz:python` syntax
   for force-including with a specified type? Or is the bare `!` form with LLM identification
   sufficient? Deferred — can be added based on user feedback.

2. **Symlink handling**: Should symlinks be followed, ignored, or flagged? Following symlinks
   risks infinite loops (symlink cycles) and duplicate processing. Ignoring them might miss
   files the user expects to be documented. Needs a decision before implementation.

3. **Large project performance**: At what project size does the walk itself become a
   bottleneck? Hashing every non-ignored file adds I/O. For most projects this is negligible
   but for monorepos with hundreds of thousands of files it could matter. Deferred — optimize
   if profiling shows a problem.
