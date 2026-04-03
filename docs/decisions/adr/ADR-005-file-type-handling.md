# ADR-005: File Type Handling and Documentation Scope

## Status
Accepted

## Context
ADRs 001-004 established the documentation pipeline, entity taxonomy, and output format — but
exclusively for source code files. A real project contains much more than source code:
configuration files (YAML, TOML, Dockerfiles), existing documentation (README, docs/),
binary assets (images, PDFs), generated directories (node_modules, build/), and tooling
config (.prettierrc, .eslintrc).

The pipeline needs clear rules for which files enter the documentation process, which are
ignored, and how non-source files are handled when they do get documented.

### Key considerations

- **Configuration files contain important knowledge.** A docker-compose.yml or Makefile often
  tells a developer more about how to work with a project than any source file. Ignoring them
  entirely would leave a gap.
- **Existing documentation is dangerous as context.** If docai reads an existing README or
  its own previously generated docs, it risks circular reasoning (documenting its own output)
  or incorporating outdated information. The source of truth should be the code itself.
- **Binary files cannot be documented from content.** An image, PDF, or font file has no
  meaningful textual structure to analyze.
- **Users need control.** Every project has unique conventions about what matters. A
  `.docaiignore` file gives users the ability to customize without requiring docai to
  anticipate every project structure.

## Options Considered

### Handling of configuration files

#### Option A: Ignore all non-source files
- **Pros**: Simple, avoids edge cases
- **Cons**: Misses valuable documentation targets. Dockerfiles, Makefiles, CI configs, and
  SQL migrations contain logic that developers need to understand.

#### Option B: Document config files at the same depth as source code
- **Pros**: Uniform treatment of all files
- **Cons**: A Dockerfile doesn't have "functions" and "classes." Forcing entity-level
  documentation on config files produces awkward, unhelpful output. Over-documents files
  that need a concise overview, not per-entity reference.

#### Option C: Document config files at module-level depth only
- **Pros**: Produces useful documentation — what does this file configure, what are the key
  settings, what would a developer need to change? Matches how developers actually think
  about config files. Avoids forcing entity taxonomy onto non-code files.
- **Cons**: Requires distinguishing "code-like config" from "tool boilerplate config," which
  is a judgment call.

### Handling of existing documentation

#### Option A: Consume existing docs as context in Pass 1
- **Pros**: The LLM gets more information about the project's purpose and conventions
- **Cons**: Existing docs may be outdated, misleading, or incomplete. If the project has
  previously generated docai output, consuming it creates a circular dependency — docai
  documenting its own output. Adds complexity to determine which docs are trustworthy.

#### Option B: Ignore existing documentation entirely
- **Pros**: docai generates from the source of truth (code) only. No risk of stale context
  or circular generation. Simple and predictable.
- **Cons**: Misses potentially useful project context. A well-written README could help the
  LLM understand the project better.

### User control over file inclusion

#### Option A: Hardcode sensible defaults, no customization
- **Pros**: Simpler to implement
- **Cons**: Every project is different. Users will inevitably want to exclude or include
  files that the defaults get wrong.

#### Option B: `.docaiignore` file with sensible defaults
- **Pros**: Familiar pattern (matches `.gitignore`), gives users full control, sensible
  defaults handle the common case without configuration
- **Cons**: Another config file to maintain, need to define the default ignore list

## Decision

### File classification

All files in a project are classified into three categories:

**1. Documented — source code files (full depth)**

All programming language source files enter the full documentation pipeline: tree-sitter
parsing, entity extraction, per-file narrative overview, per-entity reference sections.
This is the core of docai and is covered by ADRs 001-004.

**2. Documented — code-like configuration (module-level depth only)**

Files that contain logic, structure, or configuration that developers need to understand:
- Dockerfiles and docker-compose files
- Makefiles, Justfiles
- CI/CD configs (`.github/workflows/`, `.gitlab-ci.yml`, Jenkinsfiles)
- SQL migration files
- Terraform / CloudFormation / infrastructure-as-code files
- Shell scripts used for project setup or build processes

These are documented at **module-level depth only**: a concise overview of what the file
configures, what the key settings are, and what a developer would need to know or change.
No entity-level breakdown. The LLM receives the file content and produces a single narrative
summary, treated as a Module entity.

**3. Ignored**

Files that provide no documentation value or that could harm output quality:

- **Binary files**: images, PDFs, fonts, compiled assets, archives
- **Generated directories**: `node_modules/`, `build/`, `dist/`, `.git/`, `__pycache__/`,
  `target/`, `vendor/`
- **Lockfiles**: `package-lock.json`, `Cargo.lock`, `poetry.lock`, `yarn.lock`
- **Tool boilerplate config**: `.prettierrc`, `.eslintrc`, `.editorconfig`, `.gitignore`
  (standard tooling config that doesn't need project-specific documentation)
- **Existing documentation**: README files, CONTRIBUTING.md, `docs/` folders, and any
  previously generated docai output. These are not consumed as context — docai generates
  from the source of truth (code) to avoid circular reasoning and stale information.

### User control: `.docaiignore`

A `.docaiignore` file in the project root, using `.gitignore` syntax, lets users override
the defaults. Users can:
- Exclude files or directories that docai would otherwise document
- The built-in defaults handle common cases (ignoring `node_modules/`, `.git/`, binary
  file extensions, etc.) so most users won't need a `.docaiignore` at all

## Consequences

### Positive
- Config files that developers actually need to understand get documented, but at an
  appropriate depth — not forced through entity-level analysis designed for source code
- No risk of circular documentation or stale context from existing docs
- Sensible defaults mean zero configuration for most projects
- `.docaiignore` gives power users full control
- Clear classification rules make the file discovery component straightforward to implement

### Negative / Trade-offs accepted
- Ignoring existing documentation means potentially useful project context is lost. This is
  a deliberate trade-off: the risk of stale or circular context outweighs the benefit.
  The user's one-sentence project description (from the pipeline) fills the gap for
  high-level context.
- The boundary between "code-like config worth documenting" and "tool boilerplate to ignore"
  is a judgment call. The defaults will be wrong for some projects — `.docaiignore` is the
  escape hatch.
- Module-level-only documentation for config files means docai won't catch fine-grained
  issues in complex configs. This is acceptable — config files are simpler than source code
  and a concise overview is usually sufficient.
