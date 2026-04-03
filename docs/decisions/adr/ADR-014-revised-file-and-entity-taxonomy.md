# ADR-014: Revised File Classification Model and Refined Entity Taxonomy

## Status
Accepted

## Context
ADR-004 defined the original entity taxonomy (Callable, Type, Value, Module, Implementation)
and ADR-005/007 defined file classifications (source code, code-like config, ignored, unknown).
During data modeling, stress-testing these decisions against real codebases across multiple
programming paradigms revealed several issues:

**File classification issues:**
- The hard boundary between "source code" (enters Structure Extractor) and "code-like config"
  (bypasses it) was a pipeline-gating decision made too early. Discovery shouldn't decide
  extraction strategy — the Structure Extractor should.
- Binary/resource files were lumped into "ignored," making them invisible in generated docs.
  But a package summary for a directory containing assets should acknowledge what's there.
- Existing documentation (README, CONTRIBUTING) was also lumped into "ignored," but these
  files have a legitimate role in the project structure — they should appear in package
  summaries and receive Pass 1 purpose sentences.
- Config-like files (Dockerfiles, YAML, Makefiles) were treated as a monolithic category,
  but some have cross-file imports (SCSS `@use`, Makefile `include`) that should feed the
  dependency graph.

**Entity taxonomy issues:**
- Getters, setters, and properties are syntactically methods but semantically field accessors.
  Documenting them as standalone Callables with parameters and return values is misleading —
  they should be folded into their parent Type's field documentation.
- Magic methods / protocol methods (`__str__`, `toString()`, `equals()`) are boilerplate in
  most cases. Documenting them at the same depth as public API methods produces noise. But
  some (`__init__`, `__getattr__`, `__enter__`) are critical.
- Private helpers and internal functions were treated identically to public API — no signal
  for the Documentation Generator to adjust depth.
- Macros (C preprocessor, Rust `macro_rules!`, proc macros) were placed in Callable, but
  their documentation needs are fundamentally different: input patterns vs. parameters, code
  expansion vs. return value, compile-time vs. runtime behavior.
- Type aliases were placed in Type but have none of Type's meaningful fields (no fields, no
  variants, no invariants, no construction).
- The `visibility` field (`public | private | internal`) didn't capture enough about an
  entity's role to guide documentation depth decisions.
- Implementation as a category included Rust inherent impls (`impl Type`), which don't
  connect a type to a contract — they're just methods defined on a type.

### Cross-paradigm analysis

The revised taxonomy was validated against:
- **Object-oriented**: Java, C#, Python, TypeScript, Kotlin, Ruby — classes, interfaces,
  abstract classes, properties, static methods, inner classes, data classes, sealed classes,
  annotations, companion objects
- **Functional**: Haskell, OCaml, Elixir, F#, Clojure — algebraic data types, typeclasses,
  typeclass instances, pattern matching, functors, type aliases
- **Systems**: C, Rust, Go, Zig — structs, free functions, macros (both C preprocessor and
  Rust macro_rules!/proc macros), traits, impl blocks (inherent vs. trait), enums (C simple
  vs. Rust ADTs), unions, typedefs
- **Scripting**: Bash, Lua, Perl, PHP — positional arguments, exit codes, tables-as-modules,
  PHP traits, exported variables
- **Logic**: Prolog, Datalog — predicates, facts, rules, unification variables
- **SQL**: tables, views, stored procedures, triggers, constraints
- **Markup/config with logic**: HTML templates, SCSS, Terraform, Makefiles

## Decision

### Part 1: Revised File Classification Model

#### Five top-level file categories

**Processed** — any file that enters the Structure Extractor. The extraction strategy is
determined by an extraction method map (plugin registry), not by the file classification.
Every processed file gets at minimum a module-level description. Whether it also gets
entity-level documentation depends on what the extractor finds.

After extraction, processed files are subcategorized:

- **Source file** — a recognized programming language file. Gets full entity extraction,
  full import resolution, entity-level and module-level documentation. Determined by Discovery
  recognizing the file as a programming language via extension, shebang, filename map, or LLM
  identification for force-included unknowns. Examples: `.py`, `.rs`, `.js`, `.ts`, `.go`,
  `.java`, `.c`, `.cpp`, `.rb`, `.swift`, `.kt`, `.cs`, `.hs`, `.ex`.

- **Source-like config** — not a programming language, but the extractor found imports to
  other project files. No entity extraction — the file is treated as a single Module entity.
  Imports feed into the dependency graph. Gets a module-level description only. Determined
  by Tier 2 heuristic extraction finding import patterns. Examples: `.scss` with `@use`,
  HTML template with `{% import %}`, Makefile with `include`, GraphQL schema with cross-file
  references.

- **Config file** — not a programming language, no imports found. No entity extraction, no
  dependencies. Treated as a single Module entity. Gets a module-level description only.
  Examples: Dockerfile, `docker-compose.yml`, `.github/workflows/*.yml`, `pyproject.toml`,
  `Cargo.toml`, `package.json`, `tsconfig.json`, `.env.example`, plain CSS, Terraform files.

The subcategory is a computed property derived from two inputs: what the file *is* (from
Discovery — programming language or not) and what the extractor *finds* (imports or not). It
is used for user-facing display and may inform future output format differentiation, but does
not gate pipeline behavior — the extraction result does.

**Documentation** — existing project documentation. Not processed by the Structure Extractor.
Gets a Pass 1 purpose sentence derived from filename and path only (no file content is read
during Pass 1). Mentioned in package summaries. Content is never consumed as context for
other files' documentation to avoid circular reasoning.

Examples: `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/` directory contents,
`.rst` documentation files.

**Asset** — binary and resource files. Not processed individually. Filenames, types, and
counts are collected per directory and included as context in package summary generation.
This ensures directories containing assets get package summaries that acknowledge what's
there without any per-file LLM calls.

Examples: images (`.png`, `.jpg`, `.svg`, `.gif`, `.webp`), fonts (`.woff`, `.ttf`, `.otf`),
video/audio (`.mp4`, `.mp3`, `.wav`), PDFs, databases (`.db`, `.sqlite`), data fixtures
(`.csv` datasets, `.json` test fixtures, SQL seed data), archives (`.zip`, `.tar.gz`).

**Ignored** — truly invisible. Not mentioned anywhere in generated documentation, not
included in package summaries. Pruned during directory walk where possible.

Examples: generated directories (`node_modules/`, `build/`, `dist/`, `target/`,
`__pycache__/`, `.git/`, `.venv/`), lockfiles (`package-lock.json`, `Cargo.lock`,
`poetry.lock`, `yarn.lock`), tool boilerplate config (`.prettierrc`, `.eslintrc`,
`.editorconfig`, `.gitignore`, `.gitattributes`), previous docai output (`.docai/`).

**Unknown** — files that couldn't be classified by the detection stack. Warned about, skipped
from processing. Available for user override via `!` patterns in `.docaiignore`, which
triggers LLM identification validated against the known type registry.

#### Extraction method map

A plugin registry mapping file types to extraction strategies. The Structure Extractor looks
up the file's type in this map to determine how to extract structure. The map is the single
source of truth for extraction strategy.

**Tier 1 — Full tree-sitter extraction.** For first-class programming languages. Tree-sitter
grammar + entity mapping table + import pattern table + import resolution heuristics +
visibility rules. Produces full entity directory and resolved dependencies. Error handling:
ERROR nodes trigger LLM verification of entity directory (ADR-003).

v1 languages: Python, JavaScript/TypeScript, Rust, Go, Java, C/C++. All grammars bundled
with the package.

**Tier 2 — Heuristic import check.** For config-like and markup files. A small list of
regex patterns per file type checking for import-like constructs only. If no patterns match
→ return zero entities, zero imports immediately (free, instant). If a pattern matches →
escalate to LLM to resolve the import against the file manifest. Never does entity
extraction. File is subcategorized as source-like config (imports found) or config (no
imports). Each heuristic plugin is roughly 5-10 lines of configuration.

v1 heuristic plugins:

| File type | Import patterns | Behavior when no match |
|-----------|----------------|------------------------|
| SCSS/SASS/LESS | `@import`, `@use`, `@forward` | Return empty |
| HTML | `{% import`, `{% from`, `{% include` (template engines) | Return empty |
| CSS | `@import` | Return empty |
| Makefile/Justfile | `include` | Return empty |
| GraphQL | `#import`, cross-file `extend` | Return empty |
| Dockerfile | *(no patterns)* | Always return empty |
| YAML/TOML/JSON config | *(no patterns)* | Always return empty |
| SQL | *(no patterns)* | Always return empty |

**Tier 3 — LLM fallback.** For programming language files without a Tier 1 tree-sitter
config. Full entity extraction + import resolution via LLM (receives file content, file
manifest, and entity taxonomy). Only applies to source files — config-like files without a
Tier 2 plugin simply return empty results; they do not fall through to Tier 3.

**Lookup logic:** Discovery determines file type → Structure Extractor checks extraction
method map:
- Tier 1 entry found → full tree-sitter extraction
- Tier 2 entry found → heuristic import check
- No entry found AND file is a recognized programming language → Tier 3 LLM fallback
- No entry found AND file is not a recognized programming language → return empty
  FileAnalysis (config file with no entities, no imports)

**Plugin architecture from v1** — extraction method configs (both Tier 1 and Tier 2) are
loadable from external packages at runtime. Community-contributed configs conform to the
extraction method schema. Adding support for a new language or file type is a data/config
task, not a code change.

#### Changes from original ADRs (ADR-005, ADR-007, ADR-008)

- **Source code and code-like config merged into "processed"** — all enter the Structure
  Extractor. The subcategory (source file, source-like config, config file) is derived after
  extraction, not before.
- **New "asset" classification** — binary and resource files are no longer lumped with
  "ignored." Their filenames and types are included in package summaries.
- **New "documentation" classification** — existing project docs (README, CONTRIBUTING, etc.)
  are no longer lumped with "ignored." They get Pass 1 purpose sentences and appear in
  package summaries, but their content is never consumed as LLM context for other files.
- **Extraction method map replaces the source/config pipeline split** — the three-tier
  plugin system (full tree-sitter, heuristic import check, LLM fallback) determines
  extraction strategy per file type.
- **ProcessingPlan simplified** — two work item types (`file`, `package_summary`) instead of
  three (`source_file`, `config_file`, `package_summary`). The Documentation Generator
  checks the FileAnalysis to determine documentation depth.

---

### Part 2: Refined Entity Taxonomy

#### Six entity categories

The original five categories (Callable, Type, Value, Module, Implementation) are revised to
six, with the addition of Macro and significant refinements to every category.

Every entity now carries a **kind** field (specific variant within the category) and a
**role** field (documentation relevance signal). The category keeps the pipeline simple
(extraction, graph building, documentation generation work with six categories). The kind
and role fields give the Documentation Generator precise signals for depth and field
selection.

#### Roles (apply to all entity categories)

| Role | Description | Documentation behavior |
|------|-------------|----------------------|
| `public` | Part of the module's external API | Always documented, default standard depth |
| `private` | Internal to the module | Documented at reduced depth unless complexity warrants more |
| `internal` | Visible within the package but not externally | Documented at standard depth |
| `protocol` | Exists to satisfy a language convention (magic methods, operator overloads, standard trait impls) | Documented only if behavior is non-obvious; otherwise mentioned in parent Type summary |
| `accessor` | Getter/setter/property | Not emitted as standalone entity — folded into parent Type's field documentation |

Roles replace the simpler `visibility` field from ADR-004. They combine visibility with
semantic intent, giving the Documentation Generator a richer signal for depth decisions.

#### 1. Callable

Anything invoked to perform an action or compute a result.

**Kinds**: `function`, `method`, `constructor`, `destructor`, `closure`, `lambda`,
`generator`, `coroutine`, `predicate`, `trigger`, `abstract_method`

**Accessor-role handling**: Getters, setters, and properties are detected during extraction
and are **not emitted as standalone Callable entities**. They are folded into the parent
Type's field list as enriched fields (field name, type, description, and a flag indicating
computed/property access). This matches how developers think about properties — they look at
the type and see its fields, not at separate getter methods.

**Protocol-role handling**: Magic methods (`__str__`, `__repr__`, `__eq__`, `__hash__`,
`__len__`, `__bool__`, `toString()`, `equals()`, `hashCode()`, `compareTo()`, standard
`Display`/`Debug` trait impls) are emitted as entities but flagged with `role: protocol`.
The Documentation Generator decides whether to document them standalone (if behavior is
non-obvious) or mention them briefly in the parent Type summary.

Non-trivial protocol methods that always get standalone documentation: constructors
(`__init__`), attribute access overrides (`__getattr__`, `__getattribute__`), context
managers (`__enter__`, `__exit__`), call overrides (`__call__`), custom operator overloads
with non-obvious behavior, iterator/generator protocol implementations.

**Required fields** (always present):

| Field | Description |
|-------|-------------|
| `name` | Entity name |
| `summary` | One-line description of what this callable does |
| `signature` | Full signature including parameter names and types, return type |
| `visibility` | `public`, `private`, `internal` |
| `role` | `public`, `private`, `internal`, `protocol` |
| `kind` | `function`, `method`, `constructor`, etc. |
| `parent` | Enclosing type or function name; `null` for top-level functions |

**Conditional fields** (present only when relevant):

| Field | When included |
|-------|--------------|
| `parameters` | Detailed parameter descriptions (name, type, what it represents) — included for standard and rich depth, skipped for minimal |
| `return_value` | Description of what's returned and what it represents — only when non-void and non-obvious from the summary |
| `yields` | Generators/coroutines only — what values are yielded and when |
| `side_effects` | Only when the callable actually has them (IO, mutation, network, state changes). Pure functions get no side effects field. |
| `error_behavior` | Only when the callable can fail (exceptions, error returns, panics) |
| `example_usage` | Public callables with non-obvious usage patterns only |
| `dependencies_called` | Only when the callable orchestrates other project callables. Leaf functions don't list dependencies. |
| `mutates_self` | Methods only, only when they mutate |
| `decorators` | Only when present and meaningful (not markers like `@override`) |
| `is_abstract` | Abstract methods only |
| `is_static` | Static methods only |
| `is_async` | Async functions/methods only |
| `type_parameters` | Generic callables only — type params with constraints in plain language |
| `overloads` | Only when other overloads of the same name exist — list their signatures |

**Documentation depth triggers:**

- **Minimal** (summary + signature only): private helpers with obvious behavior, trivial
  protocol methods (`__str__`, `__repr__`, `toString`, `equals` with standard behavior),
  simple wrappers that delegate immediately, closures/lambdas with obvious intent.
- **Standard** (required + relevant conditional fields): public API functions, methods with
  non-trivial logic, constructors, factory methods, anything with error paths or side effects.
- **Rich** (standard + examples, edge cases, design notes): complex public APIs with
  non-obvious usage, callables with subtle behavior or important edge cases, callables where
  decorators/annotations significantly alter behavior, generators/coroutines with complex
  yield patterns.
- **Skip entirely** (not documented as standalone, mentioned in parent Type or Module):
  accessor-role entities (folded into Type fields), trivial protocol methods where behavior
  is exactly what the name implies.

**Edge cases resolved:**

- **Static methods**: Callables with `parent` set to the class, `is_static: true`,
  `mutates_self` never applies.
- **Abstract methods**: Callables with `is_abstract: true`. Documentation describes what
  the implementor is expected to do, not behavior.
- **Overloaded methods** (Java, C++): each overload is a separate Callable entity.
  The `overloads` field cross-references the other signatures.
- **Extension functions** (Kotlin, Swift): Callables with `parent` set to the extended type.
  If the extended type is external, parent is the type name as a string without a project
  file reference.
- **Lambdas assigned to variables** (`const validate = (x) => x > 0`): classified as
  Callable, not Value. The variable name becomes the entity name.
- **Default interface methods** (Java 8+): Callables with parent being the interface Type.
- **Generators/async generators**: Callables with `kind: generator` or `kind: coroutine`.
  The `yields` field replaces `return_value` for describing output.
- **Constructors vs. factory methods**: constructors are `kind: constructor`. Factory methods
  are regular methods — the LLM recognizes the pattern and documents accordingly.
- **Destructors/finalizers**: `role: protocol`, documented only if non-trivial.

#### 2. Macro

Compile-time or preprocessing code generation. Separate from Callable because documentation
concerns are fundamentally different: no runtime behavior, no typed parameters, operates on
tokens/syntax rather than values.

Note: C++ templates are **not** Macros — they are typed, part of the type system, and
classified as Types or Callables with generic type parameters.

**Kinds**: `c_macro_value` (object-like `#define`), `c_macro_function` (function-like
`#define`), `rust_declarative` (`macro_rules!`), `rust_procedural` (proc macros, derive
macros, attribute macros), `lisp_macro`

**Required fields:**

| Field | Description |
|-------|-------------|
| `name` | Macro name |
| `summary` | What this macro does / what code it generates |
| `kind` | Which kind of macro |
| `visibility` | `public`, `private`, `internal` |

**Conditional fields:**

| Field | When included |
|-------|--------------|
| `input_patterns` | What patterns or token structures the macro accepts — for function-like and Rust macros |
| `expansion_description` | Plain language description of what code the macro generates |
| `value` | `c_macro_value` only — the defined value |
| `example_usage` | When usage is non-obvious |
| `compile_time_effects` | When the macro affects compilation beyond simple expansion (conditional compilation, feature gating) |
| `replaces` | When the macro is a convenience wrapper — what code you'd write without it |

**Documentation depth triggers:**

- **Minimal**: simple value macros (`#define VERSION "1.0"`), trivial function-like macros
  that are essentially inline functions.
- **Standard**: function-like macros with meaningful logic, Rust declarative macros, derive
  macros.
- **Rich**: procedural macros that generate complex code, macros that significantly alter
  program structure, macros with multiple input patterns.

#### 3. Type

Anything defining the shape of data or a behavior contract.

**Kinds**: `class`, `struct`, `record`, `data_class`, `enum`, `union`, `interface`, `trait`,
`protocol`, `abstract_class`, `sealed_class`, `type_alias`, `named_tuple`

**Required fields:**

| Field | Description |
|-------|-------------|
| `name` | Type name |
| `summary` | One-line description of what this type represents |
| `kind` | Which kind of type |
| `visibility` | `public`, `private`, `internal` |

**Conditional fields:**

| Field | When included |
|-------|--------------|
| `fields` | All kinds except `type_alias`, `interface`, `trait`, `protocol` — the data the type holds. Each field: name, type, description, whether computed (property), default value if relevant |
| `variants` | Enums, unions, sealed classes only — each variant with associated data and meaning |
| `permitted_subtypes` | Sealed classes/interfaces only — the closed set of allowed subtypes |
| `contract_methods` | Interfaces, traits, protocols, abstract classes only — what methods an implementor must provide, with signatures and expected semantics |
| `key_methods` | Classes, structs with many methods — highlight 2-3 most important methods, not a full list |
| `construction` | When construction is non-trivial — builders, factories, validation, alternative constructors. Skip for simple types. |
| `invariants` | When meaningful constraints exist not obvious from field types (e.g., "length always > 0", "start < end") |
| `relationships` | When the type extends, implements, contains, or is contained by other project types |
| `aliases_to` | `type_alias` only — what type this aliases and why the alias exists |
| `type_parameters` | Generic types only — type params with constraints in plain language |
| `protocol_methods` | Implemented magic methods / protocol conformances, briefly listed — e.g., "supports iteration, comparison, and context manager protocol" |
| `decorators` | Only when present and meaningful (`@dataclass`, `#[derive(...)]`, etc.) |
| `is_abstract` | Abstract classes only |
| `is_partial` | Partial classes (C#) only |

**Documentation depth triggers:**

- **Minimal**: type aliases (name, summary, aliases_to only), simple data classes with
  self-descriptive field names, small enums with obvious variants, named tuples.
- **Standard**: core domain types, public API types, types with non-trivial construction or
  invariants, interfaces/traits/protocols.
- **Rich**: types with complex generic bounds, sealed class hierarchies, types with subtle
  invariants or important edge cases, types where decorators significantly alter behavior
  (e.g., `@dataclass(frozen=True, order=True)`).

**Edge cases resolved:**

- **Enums vary by language**: C enums (named integers) → `kind: enum` with minimal depth.
  Java enums (full classes) → `kind: enum` with standard/rich depth including methods.
  Rust enums (ADTs) → `kind: enum` with `variants` field including per-variant data.
- **Data classes/records**: `kind: data_class`. Auto-generated methods (`__eq__`,
  `hashCode()`) are `role: protocol` and not documented individually.
- **Sealed classes**: `kind: sealed_class` with `permitted_subtypes` field.
- **Partial classes** (C#): documented per-file with `is_partial: true`. Module-level
  description explains the split.
- **Protocols/structural typing** (Python `Protocol`, Go interfaces): `kind: protocol` or
  `kind: interface`. Documentation emphasizes the contract.
- **Getters/setters/properties**: not separate entities. Folded into the Type's `fields`
  list with a computed/property flag. A Python `@property` becomes a field entry on the
  class, not a standalone Callable.

#### 4. Value

Anything holding or providing a value, binding, or re-export at module scope.

**Kinds**: `constant`, `variable`, `static`, `export`, `re_export`, `environment_variable`

**Required fields:**

| Field | Description |
|-------|-------------|
| `name` | Value name |
| `summary` | What this value represents — not just type, but the concept it encodes |
| `visibility` | `public`, `private`, `internal` |
| `kind` | Which kind of value |

**Conditional fields:**

| Field | When included |
|-------|--------------|
| `type` | The value's type — when available and useful |
| `actual_value` | Constants and statics — the literal value. Skip for complex computed values. |
| `valid_range` | Config values, thresholds — what range of values is acceptable |
| `rationale` | Magic numbers, non-obvious constants — why this value, why not something else |
| `used_by` | Only when the value has broad cross-module impact (config that affects behavior across the project) |
| `re_exports_from` | Re-exports only — source module and original name (if renamed) |
| `is_mutable` | When the value is mutable module-level state (registries, global config objects) — flag for attention |

**Documentation depth triggers:**

- **Minimal**: constants with self-descriptive names (`MAX_RETRIES`, `DEFAULT_TIMEOUT`),
  simple re-exports, type-annotated variables where the type tells the story.
- **Standard**: configuration values, magic numbers, mutable module-level state, exported
  values that are part of the public API.
- **Rich**: rarely needed — perhaps complex configuration objects or registries central to
  the project's architecture.

#### 5. Module

The file itself as an organizational entity. Implicit — not extracted by the Structure
Extractor, created during documentation generation. Applies to all processed files (source
files, source-like config, and config files).

**Required fields:**

| Field | Description |
|-------|-------------|
| `purpose` | What problem this module solves, one paragraph |

**Conditional fields:**

| Field | When included |
|-------|--------------|
| `key_entities` | The 2-3 most important things this module provides — skip for files with 3 or fewer entities |
| `how_it_fits` | Dependencies and dependents, role in the project — skip for isolated files |
| `usage_pattern` | Entry points, common workflows — only when non-obvious |
| `limitations` | When the module has explicit scope boundaries or known gaps |

#### 6. Implementation

A syntactically separate connection between a type and a behavior contract. Only exists in
languages where the implementation is its own syntax block.

**What qualifies:**
- Rust `impl Trait for Type` → yes, Implementation entity
- Haskell `instance Typeclass Type` → yes
- Swift `extension Type: Protocol` → yes

**What does not qualify:**
- Rust `impl Type` (inherent impl) → **no**. Methods are extracted as Callables with
  `parent: Type`. An inherent impl doesn't connect a type to a contract.
- Java `class Foo implements Bar` → **no**. Documented as a `relationships` field on
  the Type entity.
- Go implicit interface satisfaction → **no**. Documented as a `relationships` field on
  the Type entity.

**Kinds**: `trait_impl`, `typeclass_instance`, `protocol_conformance`

**Required fields:**

| Field | Description |
|-------|-------------|
| `name` | Identifier (e.g., "Display for MyType") |
| `summary` | What this implementation enables |
| `connects` | Which type implements which contract |

**Conditional fields:**

| Field | When included |
|-------|--------------|
| `why` | When non-obvious — what use case this implementation enables |
| `notable_methods` | When implementation deviates from naive expectations |
| `constraints` | When the implementation is partial, lossy, or has caveats |
| `type_parameters` | When the implementation is generic |

**Documentation depth triggers:**

- **Minimal**: standard trait implementations that do the obvious thing (`impl Display`,
  `impl From<X> for Y` with straightforward conversion).
- **Standard**: implementations that enable important functionality, custom behavior.
- **Rich**: complex implementations with surprising behavior, partial or lossy
  implementations, implementations with important caveats.

### Overall documentation depth decision logic

The Documentation Generator determines depth per entity based on these signals, available
from the FileAnalysis without additional analysis:

1. **Role** — `protocol` and `private` entities default to minimal unless complexity signals
   override. `public` defaults to standard. `accessor` entities are never standalone.
2. **Kind** — constructors always get at least standard depth. Type aliases always get
   minimal. Abstract methods get minimal (they're specifications, not implementations).
3. **Entity size** — line count from the extractor. A 3-line function gets minimal. A
   50-line function gets at least standard.
4. **Parent context** — methods inside a type with many methods (above per-entity threshold)
   may get reduced depth to keep overall documentation manageable.
5. **Decorators/annotations present** — bumps depth up one level (decorators add complexity
   worth explaining).
6. **Generic type parameters present** — bumps depth up one level.

The LLM makes the final call on which conditional fields to include, but these signals are
passed as guidance in the prompt. Example prompt guidance: "This is a public method, 45
lines, async, with decorators. Document at standard-to-rich depth. Include all relevant
conditional fields."

## Consequences

### Positive
- File classification is now driven by extraction results, not upfront assumptions —
  Discovery determines file type, the extractor determines documentation depth
- Asset and documentation categories give projects a complete picture in package summaries
  without wasting LLM calls on binary files or generating circular documentation
- The extraction method map with three tiers provides the right extraction strategy per file
  type at the right cost (free for tree-sitter and trivial configs, cheap LLM for edge
  cases, full LLM only for unsupported programming languages)
- Six entity categories cover all mainstream programming paradigms without forcing
  language-specific constructs into ill-fitting categories
- The `kind` field allows precise documentation field selection within each category
- The `role` field gives the Documentation Generator clear signals for depth decisions,
  eliminating the problem of over-documenting trivial protocol methods and private helpers
- Accessors folded into Type fields match developer mental models — properties are seen as
  part of the type, not as separate methods
- Required vs. conditional field split ensures minimal documentation is always meaningful
  while rich documentation is never cluttered with empty sections
- Depth decision logic is based on signals available from extraction (role, kind, line count,
  decorators, generics) — no additional analysis pass needed

### Negative / Trade-offs accepted
- Six entity categories instead of five adds a small amount of complexity to the pipeline.
  Macros are rare in most codebases, but when present they need fundamentally different
  documentation than Callables.
- The `role` determination requires language-specific knowledge — what counts as a "protocol
  method" differs between Python, Java, Rust. The extractor's language config tables must
  include role assignment rules.
- Accessor detection and folding into Type fields adds extraction complexity — the extractor
  must recognize property patterns per language (Python `@property`, C#/Kotlin property
  syntax, Java getter/setter naming conventions) and merge them into the parent Type.
- The depth decision logic introduces subjectivity via the LLM — two runs may produce
  slightly different depth for the same entity. The signal-based guidance minimizes this
  but cannot eliminate it.

### Constraints created
- Entity extraction configs (Tier 1 tree-sitter tables) must include: kind assignment rules,
  role assignment rules, accessor detection patterns, and protocol method identification per
  language
- LLM extraction prompts (Tier 3) must include the full taxonomy with kinds and roles, plus
  guidance on accessor folding
- Documentation Generator prompt templates need per-category field sets with conditional
  inclusion logic based on kind and role
- The FileAnalysis output contract must carry kind and role per entity
- The completeness verification logic must account for accessor-role entities being absent
  from the standalone entity list (they're in the parent Type's fields instead)

## Open Questions

1. **Accessor detection accuracy**: Language-specific property patterns vary significantly.
   Python's `@property` is explicit, but Java's getter/setter convention (method named
   `getName()` on a class with a field `name`) is heuristic. How aggressive should accessor
   detection be for languages with convention-based properties? Conservative (only explicit
   syntax) is safer for v1.

2. **Protocol method list maintenance**: The list of "trivial protocol methods" that get
   skipped or minimally documented needs to be maintained per language. Should this be part
   of the language config plugin, or a global list with language-specific extensions?

3. **Macro prevalence in practice**: If macros are rare enough in most codebases, is the
   added pipeline complexity of a sixth category justified? Could be validated by analyzing
   a sample of real projects. The alternative is keeping macros in Callable with
   `kind: macro` and a different field set — less clean conceptually but simpler in the
   pipeline.
