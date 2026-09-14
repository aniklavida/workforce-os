# Build-to-release roadmap

The goal is one useful, market-ready v1.0, followed by maintenance driven by real issues, demand and contributions.

## 0. Reconcile and lock

Lock positioning, v1.0 scope, the worker schema and the review-protocol content, and make the documented Notion structure agree with the public docs.

**Done:** no unresolved product contradiction remains and the v1.0 scope is fixed. Workforce OS is a Notion structure plus skills only — no runtime, bot gateway, scheduler or chat adapters, at any version.

## 1. Structure and migration

Make setup idempotent; add the Workforce database, relation-based assignment, profile permissions and safe migration from the current structure. Decide and document the recurring-work schema (properties, template, next-occurrence rule).

**Done:** repeated setup creates no duplicates and migration preserves user data.

## 2. Operating protocol

Align AGENTS.md, profiles, commands and skills with capture, routing, handoff, permissions, multi-worker semantics and the review-protocol checklist. Add fixture workspaces and contract tests where possible.

**Done:** two distinct workers can operate the same workspace without ownership or notes collisions, and a fixture run of the review protocol produces the right actionable lines and correctly stays silent.

## 3. Cross-agent verification

Test the Claude Code plugin from a clean install. Document and, where feasible, verify the Codex `AGENTS.md` path and any other MCP-capable agent that reaches Notion. Label each path implemented-and-tested, experimental, planned or unsupported — never leave one unlabelled.

**Done:** Claude Code installation is verified end to end; Codex's documented path has been walked through at least once; every other agent path is honestly labelled.

## 4. Installation and hardening

Test Claude Code and Codex setup from clean environments; document other-agent portability accurately; test permissions, migration, disconnect and secret handling for whatever the protocol asks an agent to touch.

**Done:** documented installation/uninstall paths work and no planned capability is marketed as implemented.

## 5. Documentation, release and marketing handoff

Complete README, examples, demo, troubleshooting, contribution/security documents, metadata, release automation and clean-install evidence; tag and publish v1.0.

**Done:** a new user can understand, install and demonstrate the complete promise without private guidance.

## After v1.0

Maintain compatibility, fix reproducible bugs/security issues, review contributions and add features only from repeated user evidence.
