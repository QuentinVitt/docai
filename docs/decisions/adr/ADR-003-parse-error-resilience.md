# ADR-003: Parse Error Resilience and Entity Directory Verification

## Status
Accepted

## Context
ADR-002 established tree-sitter as the primary structure extraction tool with LLM as a fallback
for unsupported languages. However, a critical scenario was unaddressed: what happens when
tree-sitter has a grammar for the language but the source code contains syntax errors?

This is not an edge case. The developers most likely to use docai — those who don't write
documentation and need to understand unfamiliar or revisited code — are also likely to run the
tool on code that's in a work-in-progress state: missing semicolons, unclosed brackets,
incomplete function signatures.

### The core problem

Tree-sitter was designed for IDE use and includes error recovery. It doesn't simply fail on
syntax errors — it produces a partial AST with ERROR nodes marking unparseable regions, while
correctly parsing everything else. For minor errors (missing semicolons, extra commas), this
works well: the vast majority of the AST is correct.

However, certain errors — particularly at structural boundaries like function definitions —
can cause tree-sitter to misidentify entity boundaries. A missing closing brace can cause two
functions to merge into one. An incomplete function signature can cause the parser to miss an
entity entirely. The entity directory, which is foundational to the entire pipeline (context
assembly, dependency tracking, completeness verification, cache invalidation), may be silently
incorrect.

The critical insight: **we cannot detect whether structural damage occurred from tree-sitter's
output alone.** A node-based confidence ratio (error nodes / total nodes) was considered and
rejected because:
- A single ERROR node at a function boundary can merge two entities (low error count, high
  structural damage)
- Many ERROR nodes inside function bodies can leave all entity boundaries intact (high error
  count, zero structural damage)
- The metric measures parse error quantity, not structural integrity — these are different
  things

## Options Considered

### Option A: Strict — refuse to document files with parse errors
- **Pros**: Guarantees accurate entity directories
- **Cons**: Defeats the purpose of the tool. Developers with imperfect code are the primary
  users. Would be infuriating in practice.

### Option B: Tree-sitter best-effort, hope for the best
- **Pros**: Simple, no extra cost
- **Cons**: Silent incorrect entity directories lead to missing or garbled documentation with
  no indication anything went wrong

### Option C: Tree-sitter best-effort + LLM verification when errors detected
- **Pros**: Cheap targeted verification. Shows the LLM both the entity list and the source
  code — the LLM can spot merged entities, missing entities, and misidentified boundaries
  far better than any heuristic. Only triggers when errors are actually present.
- **Cons**: Extra LLM call per file with errors. Relies on LLM accuracy for verification.

### Option D: Confidence scoring with threshold-based fallback
- **Pros**: Avoids LLM calls for "minor" errors
- **Cons**: The confidence score (error nodes / total nodes) does not measure what we care
  about (entity directory correctness). Requires a tunable threshold that will be wrong in
  many cases. Adds complexity without adding reliability.

## Decision

**Option C — tree-sitter best-effort with LLM verification when ERROR nodes are present.**

The complete parsing flow has three paths with clean, binary triggers and no tunable thresholds:

```
Tree-sitter parse attempt
    │
    ├─ Grammar exists, no ERROR nodes
    │     → Trust entity directory, proceed with normal pipeline
    │
    ├─ Grammar exists, ERROR nodes present
    │     → LLM verification of entity directory (cheap, targeted call)
    │     → Merge corrections into entity directory
    │     → Proceed with normal pipeline
    │
    └─ No grammar available
          → Full LLM structural analysis (existing unsupported-language fallback from ADR-002)
```

### LLM verification call design

When ERROR nodes are detected, a targeted verification call is made. This is *not* a full
structural analysis — it's a correction pass on an already mostly-complete entity directory.
The prompt provides:

- The entity directory as extracted by tree-sitter (entity names, types, line ranges)
- The full source code of the file
- A focused question: are any entities missing, and are any listed entities actually multiple
  entities merged together?

This is cheap because:
- The output is small (only corrections, not a full entity list)
- The LLM's job is verification, not generation — easier and more reliable
- Most files with minor errors will get "no corrections needed" back

### Documentation metadata

When documentation is generated from a file that contained parse errors, the YAML frontmatter
includes a warning:

```yaml
warnings:
  - "Source file contained syntax errors — entity directory was LLM-verified. Regenerate after fixing errors for highest accuracy."
parse_errors_detected: true
```

This serves two purposes:
- The developer knows these docs may be lower-confidence
- The regeneration system can flag these files for priority re-generation even if content
  hashes haven't changed (the errors may have been fixed without changing the file's
  semantic content enough to trigger hash-based invalidation)

## Consequences

### Positive
- docai works on imperfect code — matching the reality of when developers most need
  documentation
- No tunable thresholds or heuristic scoring — clean binary decision (errors present or not)
- Leverages the existing LLM fallback path from ADR-002, keeping the pipeline uniform
- Verification is cheap and targeted, not a full re-analysis
- Metadata warnings give the user transparency about documentation confidence
- The three paths (clean parse, verified parse, full LLM fallback) cover the complete spectrum
  from perfect code to unsupported languages

### Negative / Trade-offs accepted
- Every file with any syntax error triggers an extra LLM call, even if the error didn't
  affect entity boundaries. This is a deliberate choice: the cost of an unnecessary check
  is low, the cost of a missed structural error is high.
- LLM verification is not perfect — it could miss a subtle merge or introduce a false
  correction. In practice, the combination of tree-sitter's partial AST plus LLM verification
  is much more reliable than either alone.
- Files with severe structural damage may still produce incomplete entity directories even
  after LLM verification. The documentation will be best-effort, which is still better than
  no documentation.

### Scope clarification
- Semantic errors (typos in variable names, calling a function that doesn't exist) are
  syntactically valid and tree-sitter parses them correctly. These are not docai's problem
  to solve — the tool documents what the code *does*, not what it was *intended* to do.
  Fixing bugs is out of scope.
