# ADR-004: Entity Taxonomy and Documentation Standards

## Status
Accepted

## Context
ADR-001 established that docai generates documentation at function (level 2), module/file
(level 3), and package (level 4) granularity. ADR-002 defined the output format as a hybrid
of structured frontmatter and narrative prose. However, neither ADR defined *what entities
exist* across programming paradigms, nor *what information should be documented about each*.

This matters because:
- The entity directory (from tree-sitter + LLM verification) needs to know what to look for
- The LLM needs clear guidance on what to produce for each entity type
- The output format needs consistent structure across languages
- Different programming paradigms have fundamentally different organizational units

### Cross-paradigm entity landscape

Programming paradigms define different fundamental units:
- **Object-oriented** (Python, Java, C#, TypeScript): classes, methods, interfaces, properties
- **Functional** (Haskell, Elixir, OCaml): functions, type definitions, typeclasses, modules
- **Systems** (C, Rust, Go, Zig): structs, free functions, macros, traits, impl blocks
- **Scripting** (Bash, Lua, JavaScript): functions, global variables, exports, closures
- **Logical** (Prolog, Datalog): predicates, rules, facts
- **Config/markup with logic** (SQL, Terraform, Makefiles): queries, resources, targets

A universal taxonomy must accommodate all of these without becoming unwieldy.

## Options Considered

### Entity Taxonomy Approach

#### Option A: Language-specific entity types
- **Pros**: Precise, idiomatic per language
- **Cons**: Explosion of types to support, no universal pipeline, new entity types needed
  for every language added

#### Option B: Universal categories that map from language-specific types
- **Pros**: Uniform pipeline, consistent output structure, language-specific types map into
  universal categories
- **Cons**: Some nuance lost in abstraction (e.g., Rust's impl blocks are richer than a
  generic "implementation" category)

### Documentation Depth

#### Option A: Fixed depth — every entity gets full documentation
- **Pros**: Consistent output, no judgment calls needed
- **Cons**: Produces bloated documentation for trivial entities. A helper function
  `is_empty(s) -> bool` doesn't need error behavior, side effects, and usage examples.
  Wastes tokens and clutters the output.

#### Option B: Scaled depth — LLM adjusts documentation richness to entity complexity
- **Pros**: Matches how humans document code. Simple things get simple docs, complex things
  get thorough docs. Produces more readable, less cluttered output. Cheaper — fewer tokens
  on trivial entities.
- **Cons**: Requires the LLM to judge complexity, which is subjective. Less predictable
  output structure.

### Language-Specific Features

#### Option A: Include all possible documentation aspects for every language
- **Pros**: Universal, no language-specific code paths
- **Cons**: Produces irrelevant sections (e.g., "Implementation" for Python, which doesn't
  have trait impls)

#### Option B: Language-aware specialization — omit aspects that don't apply
- **Pros**: Clean, relevant output. Doesn't confuse users with categories their language
  doesn't use.
- **Cons**: Requires knowing which aspects apply to which languages. Needs a language-specific
  configuration or detection layer.

## Decision

### Universal Entity Categories

Five universal categories that cover all programming paradigms:

**1. Callable**
Maps from: functions, methods, predicates, macros, closures, constructors, destructors,
getters/setters, coroutines, Makefile targets, SQL procedures.

Anything you *invoke* to perform an action.

**2. Type**
Maps from: classes, structs, enums, type aliases, interfaces, traits, protocols, unions,
algebraic data types, Haskell data declarations, TypeScript type/interface, Prolog compound
terms.

Anything that defines *the shape of data or a behavior contract*.

**3. Value**
Maps from: constants, file-level variables, module-level bindings, exported configuration,
environment variable declarations, static values, Terraform locals.

Anything that *holds or provides a value* at module scope.

**4. Module**
Maps from: files, packages, namespaces, Elixir/Erlang modules, Go packages, Python modules.

The file or module *itself* as an organizational entity.

**5. Implementation**
Maps from: Rust `impl` blocks, Go interface implementations, Java/C# interface
implementations, Haskell typeclass instances, Swift protocol conformances.

The *connection* between a type and a behavior contract. Language-specific — only documented
when the language has an explicit implementation concept. Omitted for languages where it
doesn't apply (Python, JavaScript, Bash, etc.).

### Decorators, annotations, generics

These are not separate entity categories. They are *complexity modifiers* on existing entities:
- Decorators/annotations (`@cache`, `@Override`, `#[derive(...)]`) are documented as part of
  the entity they decorate. A decorated function is more complex → gets richer documentation
  explaining what the decorators do.
- Type parameters/generics (`<T: Serialize>`, `T extends Entity`) are documented as part of
  the type or callable they parameterize. The LLM explains constraints in plain language.

This falls naturally out of the scaled-depth approach: these features make entities more
complex, so the LLM produces more thorough documentation for them.

### Documentation Aspects Per Category

#### Callable

| Aspect | When to include |
|--------|----------------|
| **One-line summary** | Always. What does this do in plain language. |
| **Parameters** | Always if parameters exist. Name, type, what each represents. |
| **Return value** | Always if non-void. Type and what it represents. |
| **Side effects** | Only if present. Mutation, IO, network, state changes. |
| **Error behavior** | Only if the callable can fail. What errors, under what conditions. |
| **Example usage** | Public/exported callables with non-obvious usage. Skip for simple helpers and internal callables. |
| **Dependencies called** | When the callable orchestrates other project callables. Skip for leaf functions. |
| **Visibility** | Always. Public, private, internal. |
| **Mutates self/instance** | Methods only, when applicable. |

#### Type

| Aspect | When to include |
|--------|----------------|
| **One-line summary** | Always. What concept does this represent. |
| **Purpose / when to use** | Complex types, types with non-obvious purpose, types that could be confused with similar types. |
| **Fields / attributes** | Always. Name, type, what each represents. |
| **Variants** | Enums and algebraic types only. Each variant and what it represents. |
| **Invariants** | When meaningful constraints exist (e.g., "length always > 0"). |
| **Construction** | When construction is non-trivial (builders, factories, validation). |
| **Key behaviors** | When the type has many methods — highlight the 2-3 most important. |
| **Relationships** | When the type extends, implements, contains, or is contained by other types. |
| **Contract** | Interfaces/traits/protocols only. What an implementor commits to. |

#### Value

| Aspect | When to include |
|--------|----------------|
| **What it represents** | Always. Not just name and type — the concept it encodes. |
| **Actual value or range** | Constants: the value. Config: valid range. |
| **Where it's used** | When the value has broad impact (used across modules, config that affects behavior). Skip for local constants. |
| **Why this value** | Magic numbers and non-obvious constants. Why 4096? Why 0.75? |

#### Module

| Aspect | When to include |
|--------|----------------|
| **Purpose** | Always. What problem does this module solve. One paragraph. |
| **Key entities** | Always. The 2-3 most important things this module provides. |
| **How it fits in** | Always. Dependencies and dependents, role in the project. |
| **Usage pattern** | When non-obvious. Entry points, common workflows. |
| **Limitations** | When the module has explicit scope boundaries or known gaps. |

#### Implementation

| Aspect | When to include |
|--------|----------------|
| **What it connects** | Always. Which type implements which trait/interface. |
| **Why** | When non-obvious. What use case does this implementation enable. |
| **Notable methods** | When implementation deviates from naive expectations. |
| **Constraints / limitations** | When the implementation is partial, lossy, or has caveats. |

### Documentation Depth Scaling

The LLM scales documentation richness to entity complexity. The guidance is:

**Minimal documentation** (one-line summary + parameters/fields):
- Private helper functions with obvious behavior
- Simple wrapper functions that delegate immediately
- Trivial constants with self-descriptive names
- Small data types with few fields and obvious purpose

**Standard documentation** (all applicable aspects from the tables above):
- Public API functions and methods
- Core domain types
- Functions with non-trivial logic, error paths, or side effects
- Module-level documentation

**Rich documentation** (standard + examples, edge cases, design rationale):
- Complex public APIs with non-obvious usage patterns
- Types with invariants, builders, or complex construction
- Functions with subtle behavior, important edge cases, or surprising interactions
- Decorated/annotated entities where the decorators significantly alter behavior
- Generic/parameterized entities where constraints are meaningful

The LLM determines depth based on: entity visibility (public gets more), cyclomatic complexity
(more branches → more docs), number of parameters, presence of decorators/generics, and
whether the entity name clearly communicates its purpose.

### Language-Specific Specialization

The Implementation category and certain aspects (like "mutates self") are only included when
the language has the corresponding concept. This is handled by a language-aware configuration
layer:
- If the language is known (via tree-sitter grammar or file extension), omit inapplicable
  aspects
- If the language is unknown (LLM fallback path), include all aspects and let the LLM
  determine which are relevant

This keeps output clean and relevant rather than cluttered with empty sections.

## Consequences

### Positive
- Five universal categories cover all programming paradigms without explosion of types
- Scaled depth produces human-quality documentation — thorough where it matters, concise
  where it doesn't
- Per-category documentation aspects give the LLM clear, structured guidance on what to
  produce
- Language-specific features (Implementation category, decorator handling) are accommodated
  without complicating the universal pipeline
- Decorators and generics handled naturally through complexity scaling, not as separate
  entities
- The taxonomy directly feeds into the entity directory structure from ADR-002

### Negative / Trade-offs accepted
- Depth scaling introduces subjectivity — two runs might produce slightly different levels
  of detail for the same entity
- The five categories are an abstraction — some language-specific nuance is lost (e.g., Rust
  distinguishes between inherent impls and trait impls, both map to "Implementation")
- Language-aware specialization requires maintaining a mapping of which aspects apply to
  which languages, or trusting the LLM to make that judgment

### Constraints created
- The LLM prompt for documentation generation must include the relevant documentation aspects
  table for the entity category being documented
- The entity directory from Pass 0 (ADR-002) must classify entities into these five categories
- The output format (ADR-002 hybrid) must accommodate variable-depth documentation without
  looking inconsistent
