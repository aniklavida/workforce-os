# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versions here track the **protocol and plugin**, not the user's own workspace. A minor bump never invalidates an existing Notion structure; a major bump means the field contract changed and existing workspaces need a migration note.

## [Unreleased]

## [0.1.0] — 2026-09-05

First public version.

### Added

- **`AGENTS.md`** — the operating protocol, in the [agents.md](https://agents.md/) cross-tool format so Claude, ChatGPT, Gemini, Cursor and self-hosted agents read the same file.
- **Field contract** — one shared `Status` for the user and every agent, and two separate note fields so the user's thinking and the agent's log never overwrite each other.
- **Domains** — life areas as options on one database rather than a database each. This is what lets the system cover everything without growing.
- **Three agent roles** — assistant (manages), advisor (thinks), specialist (does the work), deliberately kept apart.
- **Two skills** — `workforce-setup` builds the structure from five questions; `workforce-operate` runs it day to day.
- **Four commands** — `/capture`, `/daily`, `/review`, `/assign`.
- **`docs/STRUCTURE.md`** — the structure written out for agents that are not Claude Code.
- Claude Code plugin and marketplace manifests, MIT licence, and a `.gitignore` that is strict about tokens and Notion exports.

### Notes

Day one turns on five things: tasks, domains, today, reminders and goals. Habits, finance, health, reading, travel and contacts exist but stay off until asked for — completeness on day one is the documented reason these systems get abandoned.

[Unreleased]: https://github.com/aniklavida/workforce-os/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aniklavida/workforce-os/releases/tag/v0.1.0
