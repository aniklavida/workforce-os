# Build-to-release roadmap

The goal is one useful, market-ready v1.0, followed by maintenance driven by real issues, demand and contributions.

## 0. Reconcile and lock

Lock positioning, v1.0 scope, the worker schema, the heartbeat/channel commitment and the runtime direction, and make the documented Notion structure agree with the public docs.

**Done:** no unresolved product contradiction remains and the v1.0 scope is fixed.

## 1. Structure and migration

Make setup idempotent; add the Workforce database, relation-based assignment, profile permissions and safe migration from the current structure.

**Done:** repeated setup creates no duplicates and migration preserves user data.

## 2. Operating protocol

Align AGENTS.md, profiles, commands and skills with capture, routing, handoff, permissions and multi-worker semantics. Add fixture workspaces and contract tests where possible.

**Done:** two distinct workers can operate the same workspace without ownership or notes collisions.

## 3. Runtime, heartbeat and channels

Implement the minimal runtime, scheduler, Notion adapter and Telegram/Discord adapters with safe configuration and observability.

**Done:** scheduled heartbeat behaves correctly, sends through configured channels and remains silent when appropriate.

## 4. Installation and hardening

Test Claude Code and Codex setup from clean environments; document other-agent portability accurately; test permissions, rate limits, retries, migration, disconnect and secret handling.

**Done:** documented installation/uninstall paths work and no planned capability is marketed as implemented.

## 5. Documentation, release and marketing handoff

Complete README, examples, demo, troubleshooting, contribution/security documents, metadata, release automation and clean-install evidence; tag and publish v1.0.

**Done:** a new user can understand, install and demonstrate the complete promise without private guidance.

## After v1.0

Maintain compatibility, fix reproducible bugs/security issues, review contributions and add features only from repeated user evidence.
