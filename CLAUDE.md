# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Design Docs

- `docs/decisions/DECISIONS-SUMMARY.md` — full project summary: domain analysis, architecture decisions, data types, project organisation. Read this when starting a significant feature or when intent is unclear.
- `docs/decisions/adr/` — detailed ADRs per topic (pros/cons, alternatives considered). Each decision in the summary references the relevant ADR. Read a specific ADR only when making decisions in that area.

## Development Workflow

Before implementing any component, use the `/tdd` skill. It enters plan mode to build a scenario list (inputs, outputs, side effects, error cases), gets confirmation, writes the tests, and verifies they fail for the right reasons before implementation begins. Never write implementation code before tests exist and are confirmed failing.
