# ADR-001: Domain Model and Problem Scope for docai

## Status
Accepted

## Context
docai ("one tool to document them all") is a CLI tool that automatically generates documentation
for programming projects using LLMs. The core problem it solves: developers don't write
documentation, and when revisiting code later, understanding what functions do — especially
when they call chains of subfunctions — is tedious and time-consuming.

The documentation domain is broad, spanning inline comments, function docs, module overviews,
architecture diagrams, READMEs, and user guides. We needed to define which parts of this domain
docai addresses, what "good documentation" means in this context, and where the boundaries of
the tool lie.

### Key findings from domain research

Software documentation exists at six distinct levels:
1. Inline comments (why a line exists)
2. Function/method documentation (parameters, returns, behavior, examples)
3. Module/file documentation (purpose, exports, relationships to other modules)
4. Package/library documentation (entry point overview, public API surface)
5. Architecture documentation (component relationships, data flows, diagrams)
6. Project-level documentation (README, getting started, contribution guides)

Traditional documentation generators (Doxygen, Sphinx, Rustdoc, JSDoc) extract and format
existing comments — they don't *write* documentation. Newer AI tools (DocuWriter.ai, Bito CLI,
CodeGPT) use LLMs but mostly operate as IDE plugins or SaaS platforms, not local CLI tools,
and typically document functions atomically without understanding cross-function context.

### Constraints
- Solo developer project
- CLI tool, runs locally
- Must work across programming languages
- LLM-powered (leveraging LLM's multilingual code understanding)

## Options Considered

### Documentation Levels

#### Option A: Function-level only (level 2)
- **Pros**: Simplest scope, each function documented independently
- **Cons**: Misses the "how does this file fit together" context that makes docs useful

#### Option B: Function + Module + Package (levels 2, 3, 4)
- **Pros**: Covers the full "I don't understand this code" pain point. Module docs explain
  purpose and relationships. Package docs provide the entry point overview. Level 4 is largely
  a natural summary of level 3 docs.
- **Cons**: More complex context requirements, especially for module-level docs that need to
  understand cross-file relationships

#### Option C: All levels including architecture and README (levels 2-6)
- **Pros**: Complete documentation solution
- **Cons**: Levels 5-6 are qualitatively different (diagrams, tutorials, guides) and
  significantly expand scope

### Output Format

#### Option A: Inject documentation into source files
- **Pros**: Documentation lives with the code, follows language conventions (docstrings, JSDoc,
  `///` comments), visible in IDEs
- **Cons**: Modifies user's source files, requires language-specific formatting knowledge for
  every supported language, may clutter code the user prefers clean

#### Option B: External documentation files (e.g., markdown mirroring source tree)
- **Pros**: Language-agnostic, doesn't touch source code, clean separation of concerns, can
  be regenerated freely without risk to source
- **Cons**: Can drift out of sync with code, requires a separate location and structure,
  less visible during daily coding

#### Option C: Internal representation rendered to either format
- **Pros**: Flexible, supports both use cases
- **Cons**: More complex for v1, designing for both outputs before validating either

### Language Support

#### Option A: Single-language focus (e.g., Python or Rust)
- **Pros**: Can leverage language-specific parsers, produce idiomatic output, handle edge cases
- **Cons**: Limited audience, misses docai's key differentiator

#### Option B: Universal via LLM understanding
- **Pros**: Works for any language the LLM understands, huge differentiator over traditional
  tools that need language-specific parsers. One tool for polyglot developers and mixed-language
  projects.
- **Cons**: Cannot produce language-idiomatic documentation formats without language-specific
  knowledge. Generic output quality vs. idiomatic quality trade-off. Dependency/call graph
  extraction without language-specific parsing is a hard problem.

## Decision

**Documentation levels**: Option B — levels 2 (function), 3 (module/file), and 4 (package).
Levels 5 and 6 (architecture docs, README generation) are explicitly planned as future features
but out of scope for v1.

**Output format**: Option B for v1 — external documentation files. This avoids the
language-specific formatting problem and doesn't modify user source code. Future versions will
add Option A (source injection) as a user-configurable output mode, at which point
language-specific formatting (Python docstrings, JSDoc, Rust `///`, etc.) will need to be
implemented per language.

**Language support**: Option B — universal language support via LLM. v1 targets "good generic
documentation for any language." Language-specific polish (idiomatic doc formats, convention
awareness) will be added incrementally as language-specific modules.

## Consequences

### Positive
- Clear, achievable v1 scope covering the core pain point (function and module comprehension)
- External documentation is safe (never modifies source) and language-agnostic
- Universal language support via LLM is a strong differentiator in the market
- Level 4 docs are a natural rollup of level 3, minimal extra effort
- Future features (inline injection, README, architecture diagrams, onboarding assistant) are
  not blocked by any v1 decisions

### Negative / Trade-offs accepted
- External docs can drift out of sync — regeneration strategy needed (open question)
- Universal language support means v1 docs won't be idiomatic for any specific language
- Without language-specific parsing, dependency graph extraction is a hard problem that
  needs to be solved (see open questions)
- Level 4 (package docs) requires understanding multi-file structure, not just individual files

### New constraints created
- Need a strategy for extracting code structure (imports, call graphs, type definitions)
  that works across languages
- Need to define what an external documentation file looks like concretely (output format spec)
- Need a regeneration / cache invalidation strategy for when source code changes

## Open Questions

1. **Structure extraction method**: How does docai extract dependency graphs, function
   signatures, and call relationships across languages? Candidates: tree-sitter (lightweight
   AST for ~200 languages), LLM-based analysis pass, or simple regex/heuristic-based import
   detection. This is the most consequential open technical decision.

2. **Concrete output format**: What exactly does a generated documentation file look like?
   Need to sketch a concrete example for a real file to validate the design.

3. **Regeneration strategy**: When source code changes, does docai regenerate everything or
   only affected files? This determines whether docai needs to track state (hashes, dependency
   graph cache) between runs.

4. **Analysis pipeline ordering**: The proposed bottom-up approach (document leaf files first,
   use their docs as context for dependent files) is sound but has challenges: circular
   dependencies, few true leaf nodes in practice, and tension with top-down human reading
   order. Needs refinement.

5. **Context window management**: For large codebases, how does docai determine the minimum
   context an LLM needs to document a given code element accurately? This is tightly coupled
   to the structure extraction decision.
