# Workforce OS — public product specification

**Status:** Draft  
**Release target:** Complete public v1.0

## Product definition

Workforce OS coordinates a configurable workforce of AI agents and people through a shared Notion system. It turns rough input into structured work, assigns ownership, scopes context by domain, preserves handoffs and produces a useful heartbeat without requiring the user to maintain database fields manually.

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
- Silence is valid when the heartbeat finds nothing useful.
- Only tested installation paths are described as supported.

## Core concepts

| Concept | Meaning |
|---|---|
| Workforce | All assignable agents and people |
| Worker | One agent or person with a profile |
| Role | Assistant, Advisor or Specialist |
| Channel | Claude Code, Codex, Telegram, Discord, CLI or another adapter |
| Domain | Navigation and context-loading boundary |
| Task | One item in the shared work database |
| Handoff | Reassignment with a recorded reason |
| Heartbeat | Scheduled review and optional notification |

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

### Heartbeat

A scheduled run evaluates overdue work, work due soon, stalled work, waiting-on-user items, recent completions and suspiciously empty plans. It sends three to five useful lines through the configured channel or remains silent.

## Complete v1.0 scope

- Idempotent setup in the user's own Notion workspace.
- Tasks, Workforce, Domains, Goals, Knowledge, Profile and Logs structures.
- Relation-based worker assignment and domain-scoped permissions.
- Assistant, Advisor and Specialist operating profiles.
- Capture, assignment, execution, handoff, review and heartbeat protocols.
- Claude Code plugin with verified clean installation.
- Documented and tested Codex/manual AGENTS.md setup.
- Pluggable channel/runtime boundary.
- Scheduled heartbeat runtime.
- Telegram and Discord notification/interaction adapters.
- Safe configuration, secret handling and disconnect/uninstall guidance.
- Migration from the current select-based assignment structure.
- Examples, troubleshooting, contributor documentation and release automation.

## Current implementation truth

The repository currently contains the operating protocol, Claude Code plugin metadata, agent profiles, commands and Markdown skills. It does not yet contain the v1.0 heartbeat runtime, Telegram/Discord integration, relation-based Workforce migration or verified cross-agent installers.

## Outside v1.0

- A proprietary Notion replacement or hosted project-management database.
- Built-in frontier AI models.
- Enterprise billing, organization administration or complex compliance controls.
- Broad integrations beyond the verified initial agent and channel adapters.
- Claims that every agent host works without host-specific installation testing.

## Version 1.0 acceptance

- Fresh setup creates the documented structure without duplicates.
- Rough input becomes a structured, assigned task without manual field editing.
- Two workers cannot silently overwrite user notes or each other's ownership.
- Handoffs preserve a reason and correct ownership.
- Domain permissions prevent undeclared context loading.
- Heartbeat runs on schedule, reports only actionable items and can remain silent.
- Telegram and Discord adapters pass end-to-end tests with safe secret handling.
- Claude Code and Codex installation paths are tested from clean environments.
- Disconnect/uninstall instructions remove access without deleting user data.
- README claims match demonstrated behavior.
- Release, demo, licence, security policy and changelog are published.
