# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Design Docs

- `docs/decisions/DECISIONS-SUMMARY.md` — full project summary: domain analysis, architecture decisions, data types, project organisation. Read this when starting a significant feature or when intent is unclear.
- `docs/decisions/adr/` — detailed ADRs per topic (pros/cons, alternatives considered). Each decision in the summary references the relevant ADR. Read a specific ADR only when making decisions in that area.

## Config

- `docs/CONFIG-REGISTRY.md` — running notes on everything that should be configurable. Update this as components are built, before the config system is implemented.

## Development Workflow

When starting work on a new feature or issue, always create the branch with:

```
gh issue develop <number> --checkout
```

This links the branch to the GitHub issue and ensures PRs merged from it automatically close the issue.

### Component design discussion (before any tests)

Before touching `/tdd`, discuss the component structure with the user:
1. What classes and public methods does this component need?
2. What is the rough responsibility of each?

Do not proceed to testing until the user confirms the structure.

### Method-by-method TDD rhythm

Work through each method one at a time:
1. **Discuss the interface** — inputs, return type, side effects, errors raised
2. **Confirm** — wait for explicit user confirmation before proceeding
3. **Use `/tdd`** — write and verify tests for that method only
4. **Implement** — implement only what the tests require
5. **Repeat** for the next method

Never invoke `/tdd` for multiple methods at once. Never write implementation code before tests exist and are confirmed failing.
