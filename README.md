# Workforce OS

**Coordinate a workforce of AI agents and people through Notion.**

Workforce OS is an open operating protocol and Claude Code plugin for turning rough instructions into structured work, routing it to the right worker, preserving handoffs and keeping the shared Notion system accurate.

> **Pre-release:** the protocol, Claude Code plugin, commands and setup/operation skills exist. The planned bot gateway, scheduled heartbeat and verified cross-agent installers do not exist yet. Do not treat this repository as a finished release.

## The problem

Work performed through AI agents is easily trapped in chat history. Ownership becomes unclear, agents collide, context is repeatedly reloaded, and the user becomes responsible for maintaining the system that was supposed to help them.

Workforce OS gives agents and people one system of record with explicit roles, assignments, domain-scoped context and handoff rules.

## Core model

- **Assistant** — captures, structures, routes and monitors work.
- **Advisor** — reviews direction and raises useful concerns.
- **Specialist** — performs assigned work and hands back evidence.
- **Worker** — an agent or person with a profile, role, channel, permissions and domain scope.
- **Domain** — both human navigation and the boundary for loading context.
- **Task** — one record in the shared task database.
- **Heartbeat** — a scheduled review that stays silent when nothing deserves attention.

## Current repository contents

- [`AGENTS.md`](AGENTS.md) — the operating contract.
- [`docs/STRUCTURE.md`](docs/STRUCTURE.md) — current Notion structure.
- `agents/` — assistant, advisor and specialist profiles.
- `commands/` — capture, daily review, planning review and assignment flows.
- `skills/` — Claude Code setup and operating skills.
- `.claude-plugin/` — Claude Code plugin metadata.

## Current installation status

### Claude Code

The plugin is packaged for Claude Code, but a clean-install release has not yet been published. After the first verified release, the intended command will use the real repository owner:

```text
/plugin marketplace add aniklavida/workforce-os
/plugin install workforce-os
```

### Other agents and bots

`AGENTS.md` and `docs/STRUCTURE.md` are portable instructions. Automated installation and verified runtime support for Codex, other coding agents, Telegram and Discord are planned for v1.0 and must be tested before they are advertised as supported.

## Version 1.0 direction

Version 1.0 will complete the Workforce database and relation-based assignment model, idempotent Notion setup, cross-agent installation guidance, scheduled heartbeat, Telegram/Discord channel adapters, permissions and a full clean-install/release proof.

See:

- [Product specification](docs/SPEC.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Build-to-release roadmap](docs/ROADMAP.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)

## Licence

MIT. See [LICENSE](LICENSE).
