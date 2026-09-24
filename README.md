# Workforce OS

**Coordinate a workforce of AI agents and people through Notion.**

Workforce OS is an open operating protocol and Claude Code plugin for turning rough instructions into structured work, routing it to the right worker, preserving handoffs and keeping the shared Notion system accurate.

> **Pre-release:** The protocol, Claude Code plugin metadata, commands and setup/operation skills exist in this repository. No release has been published, no clean-install evidence exists yet, and no demo exists. Clean-install verification for Claude Code, and any support for Codex or other MCP-capable agents, are planned. Do not treat this repository as a finished release.

## What this is, and is not

Workforce OS is a Notion structure plus an operating protocol, agent profiles, commands and setup/operation skills. That is the whole product.

It ships **no runtime, no bot gateway, no scheduler and no Telegram/Discord adapters.** Scheduling and chat channels come from whichever agent you connect — Claude Code, Codex or another MCP-capable agent — not from this project. An agent that can run on a schedule and reach Notion should be able to run the Workforce OS review protocol; that scheduling capability is the agent's, not something installed from here. This has been run with Claude Code only — every other host is planned and unverified.

## The problem

Work performed through AI agents is easily trapped in chat history. Ownership becomes unclear, agents collide, context is repeatedly reloaded, and the user becomes responsible for maintaining the system that was supposed to help them.

Workforce OS gives agents and people one system of record with explicit roles, assignments, domain-scoped context and handoff rules.

## Core model

- **Assistant** — captures, structures, routes and monitors work.
- **Advisor** — reviews direction and raises useful concerns.
- **Specialist** — performs assigned work and hands back evidence.
- **Worker** — an agent or person with a profile, role, channel, permissions and domain scope. Every worker is a row in the Workforce database.
- **Domain** — both human navigation and the boundary for loading context.
- **Task** — one record in the shared task database, assigned to exactly one worker through the `Assigned To` relation.
- **Heartbeat** — a review protocol: a checklist for overdue, due-soon, stalled and waiting work, and a rule to stay silent when nothing deserves attention. Your connected agent runs it on its own schedule; Workforce OS does not schedule anything itself.

## Current repository contents

- [`AGENTS.md`](AGENTS.md) — the operating contract.
- [`docs/STRUCTURE.md`](docs/STRUCTURE.md) — current Notion structure.
- `agents/` — assistant, advisor and specialist profiles.
- `commands/` — capture, daily review, planning review and assignment flows.
- `skills/` — Claude Code setup and operating skills.
- `scripts/workforce_acceptance.py` — acceptance test suite proving public documentation claims against fixtures.
- `scripts/workforce_schema.py` — the Workforce database schema, `Assigned To` relation payloads, and the assignment gate; `--dry-run` and `--self-test` run without a workspace, `--live` creates the database once a credential is supplied.
- `scripts/workforce_setup.py` — idempotent setup orchestration that builds the entire structure from five answers, discovers markers, reconciles existing objects, and converges with zero duplicates.
- `scripts/workforce_migration.py` — select-to-relation migration preserving user-authored notes byte-for-byte.
- `scripts/workforce_permission.py` — three-layer permission engine (domain scope, declared read scope, action gate) and multi-worker queue isolation.
- `scripts/workforce_content_boundary.py` — deterministic prompt injection boundary treating untrusted content as data rather than instructions.
- `scripts/notion_roundtrip_proof.py` — a throwaway probe that measures Notion rate limits and formatting round-trip fidelity, feeding [`docs/NOTION_ROUNDTRIP.md`](docs/NOTION_ROUNDTRIP.md).
- `.claude-plugin/` — Claude Code plugin metadata.

## Acceptance test suite

Every public claim made by this project is verified against fixture Notion workspace state with one command:

```bash
python3 scripts/workforce_acceptance.py
```

The suite runs nine tests (eight execution tests post-rescope plus a claim-by-claim README audit):
1. **Fresh setup:** builds the complete Notion structure from five answers with zero manual fixes.
2. **Zero duplicates:** re-running setup reconciles existing objects and produces zero duplicate databases or pages.
3. **Capture transformation:** rough, half-formed input produces a structured task (next action, done-condition, domain, dates) without manual field editing.
4. **Queue isolation:** a task assigned to a worker is read and executed by that worker only; cross-worker execution is rejected.
5. **Declared read scope:** an agent working a task loads only its Domain's declared pages (verified via fixture transcript); undeclared or sensitive pages (`Profile`) are blocked.
6+7. **Review protocol & silence rule:** evaluates overdue, due-soon, stalled, and waiting work to produce 3–5 lines, and produces zero lines (silence) when nothing qualifies — verified without a scheduler, daemon, or deployment.
8. **Interruption recovery:** mid-setup API interruption generates a clear what-was-built report and subsequent re-run resumes cleanly without duplicating objects.
9. **Public claim audit:** audits this README claim by claim, verifying that every demonstrated behavior has a passing test and every unverified path is explicitly labelled planned or pre-release.

## Current installation status

No release has been published yet, no clean-install evidence exists, and no demo exists.

### Claude Code

The plugin is packaged for Claude Code, but a verified release has not yet been published. Claude Code is the only active development and test path today. Installation commands will be documented once the first verified release is published.

### Codex and other MCP-capable agents

`AGENTS.md` and `docs/STRUCTURE.md` are portable Markdown — no plugin required. Codex reads `AGENTS.md` directly by convention; any other agent that can read files and reach Notion over MCP could follow the same protocol. This path is **planned, not yet verified end to end** — Claude Code is the only tested path today, and all other agent hosts are planned. Chat delivery is whatever your agent already supports; Workforce OS has no channel code of its own.

## Version 1.0 direction

Version 1.0 will complete verified cross-agent installation guidance (Claude Code today, Codex and others as they are tested) and a full clean-install/release proof. The Workforce database, relation-based assignment model, idempotent setup, permissions, handoffs, and content boundaries are now implemented and verified in the acceptance suite against fixtures; live workspace creation remains to be confirmed once credentials are supplied. Version 1.0 will not add a runtime, a scheduler or channel adapters — those stay out of scope permanently.

See:

- [Product specification](docs/SPEC.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Build-to-release roadmap](docs/ROADMAP.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)

## Licence

MIT. See [LICENSE](LICENSE).
