# Workforce OS — public product specification

**Status:** Draft  
**Release target:** Complete public v1.0

## Product definition

Workforce OS coordinates a configurable workforce of AI agents and people through a shared Notion system. It turns rough input into structured work, assigns ownership, scopes context by domain, preserves handoffs and defines a review protocol, without requiring the user to maintain database fields manually.

Workforce OS is a Notion structure, an operating protocol, agent profiles, commands and skills — nothing else. It builds no runtime, no bot gateway, no scheduler and no chat-channel adapters. It works with any agent that reaches Notion over MCP, because the protocol is portable Markdown; scheduling and chat delivery are that agent's own capability.

It is not positioned as a generic life-OS template. A user may organize personal or professional work, but the product's distinguishing promise is multi-worker coordination.

## Primary users

- Technical Claude, Codex and AI-agent users who already use Notion.
- Individuals managing several projects or contexts through multiple agents.
- Later, small teams mixing agents and human collaborators.

## Jobs to be done

1. Capture an incomplete thought without filling a form.
2. Turn it into a task with an actionable next step and done condition.
3. Route it to a named agent or person.
4. Let each worker load only relevant domain context.
5. Preserve the reason and state when work is handed off.
6. Surface due, stalled, waiting and recently completed work once a day.
7. Keep the shared records correct without manual field maintenance.

## Product principles

- The user speaks naturally; the agent maintains the fields.
- Missing information becomes a concise question in chat, never an invented value.
- Notion stores state; active questions stay in the user's current channel.
- One task database and one status contract serve users and workers.
- Context is domain-scoped by default.
- External, destructive or irreversible actions require approval.
- Silence is valid when the review protocol finds nothing useful.
- Only tested installation paths are described as supported.

## Core concepts

| Concept | Meaning |
|---|---|
| Workforce | All assignable agents and people |
| Worker | One agent or person with a profile |
| Role | Assistant, Advisor or Specialist |
| Channel | Whichever host or chat surface a worker uses — Claude Code, Codex, Telegram, Discord, CLI or another — supplied by that agent, not built by Workforce OS |
| Domain | Navigation and context-loading boundary |
| Task | One item in the shared work database |
| Handoff | Reassignment with a recorded reason |
| Heartbeat | A review protocol — checklist and silence rule — that the connecting agent runs on its own schedule |

## Information architecture

```text
Home          today, waiting, upcoming and recent progress
Tasks         one shared work database
Workforce     worker profiles, roles, channels and permissions
Domains       one page per context boundary
Goals         desired outcomes
Knowledge     durable working context
Profile       sensitive context, denied by default
Logs          daily activity and periodic summaries
```

## Task contract

The task database includes title, status, assigned worker, domain, priority, type, start/due dates, done condition, separate user and agent notes, and completion date. `Assigned To` should relate to the Workforce database so assignment resolves to a real profile rather than a hard-coded select option.

## Worker profile

Every worker has a name, kind (`Agent` or `Human`), role, channel, permitted domains, capabilities, active/paused status and full profile instructions. Permission defaults are restrictive: an empty domain scope grants access to nothing, and sensitive domains require explicit access.

## Core workflows

### Capture → structure → assign

Create the record immediately from available context, infer only what is supported, ask at most a few necessary questions in chat, write the answers and assign the correct worker.

### Worker execution

Read assigned non-done work, respect future start dates, mark active work in progress, load only the declared domain context, keep agent notes current and request approval for external/destructive actions.

### Handoff

Record the reason, change the assigned worker and preserve task status unless the workflow itself changed.

### Heartbeat (review protocol)

A run — triggered by whatever schedule the connecting agent provides, not by Workforce OS — evaluates overdue work, work due soon, stalled work, waiting-on-user items, recent completions and suspiciously empty plans. It reports three to five useful lines through the agent's own chat surface or remains silent. Workforce OS defines the checklist and the silence rule; the agent supplies the schedule and the channel.

## Complete v1.0 scope

- Idempotent setup in the user's own Notion workspace.
- Tasks, Workforce, Domains, Goals, Knowledge, Profile and Logs structures.
- Relation-based worker assignment and domain-scoped permissions.
- Assistant, Advisor and Specialist operating profiles.
- Capture, assignment, execution, handoff, review and heartbeat (review-protocol) content.
- Claude Code plugin with verified clean installation.
- Documented Codex/manual `AGENTS.md` setup, verified where feasible before release.
- Safe configuration, secret handling and disconnect/uninstall guidance for whatever the protocol asks an agent to touch.
- Migration from the current select-based assignment structure.
- Examples, troubleshooting, contributor documentation and release automation.

## Explicitly out of scope, permanently

- A runtime process, bot gateway or scheduler of any kind.
- Telegram, Discord or any other chat-channel adapter.
- Anything that would require Workforce OS to run continuously rather than be read and executed by a connecting agent.

These are not "not yet built" — they are not part of this product. An agent's own scheduling and chat capability is what carries the review protocol and delivers its output.

## Current implementation truth

The repository currently contains the operating protocol, Claude Code plugin metadata, agent profiles, commands and Markdown skills. It does not yet contain the relation-based Workforce migration or a verified Codex/other-agent installation path.

## Outside v1.0

- A proprietary Notion replacement or hosted project-management database.
- Built-in frontier AI models.
- Enterprise billing, organization administration or complex compliance controls.
- A runtime, scheduler or chat-channel adapter of any kind (see "Explicitly out of scope" above).
- Claims that every agent host works without host-specific installation testing.

## Version 1.0 acceptance

- Fresh setup creates the documented structure without duplicates.
- Rough input becomes a structured, assigned task without manual field editing.
- Two workers cannot silently overwrite user notes or each other's ownership.
- Handoffs preserve a reason and correct ownership.
- Domain permissions prevent undeclared context loading.
- The review protocol, run by a connecting agent on its own schedule, reports only actionable items and can remain silent — verified against fixture data.
- Claude Code installation is tested from a clean environment; Codex's `AGENTS.md` path is documented and tested where feasible.
- Disconnect/uninstall instructions remove access without deleting user data.
- README claims match demonstrated behavior.
- Release, demo, licence, security policy and changelog are published.
