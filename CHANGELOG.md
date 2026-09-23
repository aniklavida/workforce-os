# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions here track the **protocol and plugin**, not the user's own workspace. A minor bump never invalidates an existing Notion structure; a major bump means the field contract changed and existing workspaces need a migration note.

## [Unreleased]

### Changed

- **`Assigned To` is now a relation to a Workforce database.** The old hard-coded select (the user's name plus a fixed trio of agent options) is replaced. Every worker — agent or human — is a row in the Workforce database carrying `Kind`, `Role`, `Channel`, `Domains`, `May approve`, `Capabilities` and `Status`, with the worker's full instructions in the row page body. That is what lets a user add a worker entirely from Notion with no repository change. The setup skill creates the database, every property carries a Notion description naming who writes it, and a migration from the old select is documented. `Domains` empty means none and a `Paused` worker receives no new assignments; the Assistant applies that gate at assignment time. The schema has been checked locally only — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#verification-status-of-the-workforce-schema).
- **Documentation claims aligned with verified implementation.** Removed premature installation commands from the README until a release is published, explicitly documented the absence of clean-install evidence and demos, and labelled non-Claude Code agent paths as planned and unverified across all public documentation.
- **Scope narrowed to Notion structure plus skills.** Workforce OS is now defined as a Notion workspace structure, an operating protocol, agent profiles and commands, and Claude Code setup/operation skills — nothing else. Earlier drafts of the docs described a planned runtime, a scheduled heartbeat runtime and Telegram/Discord channel adapters; none of that is in scope any more, at any version. Scheduling and chat delivery are the connecting agent's own capability. The "heartbeat" is now documented as a review protocol — a checklist and a silence rule — that an agent runs on its own schedule, not something Workforce OS runs itself.
- **Notion connectivity named as one path.** `docs/ARCHITECTURE.md` now documents the single consumer path — the agent already connected to Notion, defaulting to the official remote Notion MCP with OAuth — and states plainly that there is no separate heartbeat or runtime consumer, citing the 2026-09-15 locked decision. The sunsetting local `notion-mcp-server` is noted only as an unmaintained fallback.
- **API addressing moved to the data source.** The 2025-09-03 Notion API makes `data_source` primary; the docs, the setup skill and `.env.example` now direct all read/write operations at a `data_source_id` rather than the old `database_id`.

### Added — written, not yet released

Everything below exists in the repository. None of it has been tagged or
published as a release, so it is listed here rather than under a version.

- **`AGENTS.md`** — the operating protocol, in the [agents.md](https://agents.md/) cross-tool format for cross-agent compatibility (Claude Code is the only tested path today; support for other agents is planned).
- **Field contract** — one shared `Status` for the user and every agent, and two separate note fields so the user's thinking and the agent's log never overwrite each other.
- **Domains** — life areas as options on one database rather than a database each. This is what lets the system cover everything without growing.
- **Three agent roles** — assistant (manages), advisor (thinks), specialist (does the work), deliberately kept apart.
- **Two skills** — `workforce-setup` builds the structure from five questions; `workforce-operate` runs it day to day.
- **Four commands** — `/capture`, `/daily`, `/review`, `/assign`.
- **`docs/STRUCTURE.md`** — the structure written out for agents that are not Claude Code (planned, unverified).
- **`scripts/workforce_schema.py`** — the Workforce database and `Assigned To` relation payloads, the assignment gate, and a `--dry-run` / `--self-test` that run with no workspace. The `--live` path creates the database once a credential is supplied; it has not been executed here, and the document says so.
- **`scripts/workforce_setup.py`** — idempotent setup orchestration that builds the entire Workforce OS structure from five short answers, discovers parent page markers, reconciles existing objects with zero duplicates, enforces mandatory Domain context routing declarations, and resumes cleanly after interruptions. Tested via `--self-test` and `--dry-run`.
- **`scripts/workforce_migration.py`** — migration tool moving an existing workspace from legacy select-based `Assigned To` to the new Workforce relation. Preserves user-authored `Notes` and `Agent Notes` byte for byte, maps select options to worker rows (mapping the user to `Kind = Human`), reports unmatched values without guessing or dropping them, generates a reversal log for rollback, and guarantees idempotent resumption after interruption. Tested via `--self-test` and `--dry-run`.
- **`scripts/workforce_permission.py` and permission enforcement model** — three layers of permission: domain scope (acting on tasks; defaults deny; empty `Domains` grants access to nothing and states why in one line), read scope (context loading; mechanically checked against Domain page declared context; undeclared pages strictly out of scope), and an action gate (destructive, external, or irreversible actions require chat approval unless `May approve` is explicitly enabled). Protects the sensitive `Profile` domain (granted to nobody by default, deliberate loggable grant), ensures worker revocation removes integrations without deleting user data or tasks, strictly forbids credentials in the model, and guarantees all permission state is legible directly in Notion. Tested via `--self-test` and `--dry-run`.
- **Handoff and multi-worker safety enforcement** — runtime enforcement of multi-worker queue discipline and handoff protocol in `scripts/workforce_permission.py`. Two distinct workers operate a shared workspace with strict queue isolation (`Assigned To` matching worker and `Status ≠ Done`), future start dates enforce waiting, and existing in-progress work requires checking agent notes first. Reassignments require a first-class handoff event carrying a non-empty reason recorded in `Agent Notes` while preserving `Status` and leaving `Notes` untouched. The note field separation invariant strictly prevents agents from modifying the user-only `Notes` field. Role separation is mechanically enforced: Assistant cannot perform specialist execution work (research, writing, code), Advisor cannot trigger actions or maintain fields, and Specialist cannot mark tasks `Done` when approval was required and not yet granted. Confirms the locked decision that `Assigned To` single-property relation provides single ownership without lock or claim fields. Tested via `--self-test` and `--dry-run`.
- **`scripts/notion_roundtrip_proof.py`** and **`docs/NOTION_ROUNDTRIP.md`** — a throwaway, paginated measurement script and the document it fills: it writes a task row with every formatting primitive the schema uses, reads it back, and records what survived and how the rate limit presented itself. The live run has not been executed yet; the document states that plainly and gives the one-command procedure.
- Claude Code plugin and marketplace manifests, MIT licence, and a `.gitignore` that is strict about tokens and Notion exports.

### Notes

Day one turns on five things: tasks, domains, today, reminders and goals. Habits, finance, health, reading, travel and contacts exist but stay off until asked for — completeness on day one is the documented reason these systems get abandoned.

[Unreleased]: https://github.com/aniklavida/workforce-os/commits/main
