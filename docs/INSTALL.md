# Install Workforce OS by prompt

Workforce OS is one Notion structure and one operating protocol. There are two
front doors to the same build, and one source of instructions.

- **The instruction (this page)** — paste one line into the agent you use, once
  it can read files and reach Notion over MCP.
- **The Claude Code plugin (convenience)** — a wrapper around the same build,
  not the only real path.

Neither front door owns the specification. The single source is
[`AGENTS.md`](../AGENTS.md) (the operating protocol) and
[`docs/STRUCTURE.md`](STRUCTURE.md) (the structure to build). This page points
at them. It does not restate them, so the two can never drift apart.

## The instruction

> Read this page and install Workforce OS for me.

That is the whole instruction. Everything below is what it means.

## Before you start

Confirm the agent has Notion write access. If it does not, stop and say how to
connect it — do not build a partial structure.

Read [`AGENTS.md`](../AGENTS.md) and [`docs/STRUCTURE.md`](STRUCTURE.md) first.
They are the specification. Build from them, never from memory.

## The five questions (ask first)

Ask these in plain language, then build from the answers. Never ask the user to
fill a field or a form; if the answers come back short or vague, write them up
properly yourself.

1. What are the main areas of your life right now? (Their Domains — expect three
   to eight, in their words.)
2. What should your assistant call you?
3. Where do you want the daily message — here in this chat, or wherever your
   agent already delivers messages?
4. What is the one thing you are actually working toward?
5. Which workers do you have, or want? (If they do not know, create only the
   Assistant.)

## Build order

Follow this order so nothing is orphaned if the build stops halfway. It is the
same order the plugin's build script uses (`scripts/workforce_setup.py`).

1. Marker block on the parent page (`[workforce-os:root]`).
2. Workforce database (eight properties plus field descriptions).
3. Worker rows: a `Kind = Human`, `Channel = None` row for the user (question 2),
   and one row per answer to question 5.
4. Task database, with `Assigned To` as a Relation → Workforce.
5. Task views: Today, My Tasks, Agent Tasks, one per Domain, Board, Calendar,
   Someday.
6. Section pages: Domains, Goals, Knowledge, Profile, Logs.
7. Domain pages under Domains, each declaring its agent read context.
8. Sections database and gallery navigation view (properties: Section, Group, Order, What it is; worker startup briefs in Workforce rows).
9. Initial task created end to end.

## Idempotency rule

The parent page carries the marker `[workforce-os:root]`.

Before creating anything, search for that marker or existing children
(`Workforce`, `Tasks`, `Domains`, …). If found, reconcile — add missing
properties, options and views. Never create a duplicate database or page. If
fresh, create the marker and build in the order above. Re-running must converge
with zero duplicates.

Every destructive or overwriting step requires explicit confirmation first.

## What gets built

The exact property tables, views, page list, worker schema, assignment gate and
permission model live in [`docs/STRUCTURE.md`](STRUCTURE.md) and
[`AGENTS.md`](../AGENTS.md). This page deliberately does not copy them.

## Migrating an existing select

If `Assigned To` already exists as a select, follow the four-step migration in
[`skills/workforce-setup/SKILL.md`](../skills/workforce-setup/SKILL.md) and
`scripts/workforce_migration.py`. Never delete the legacy property before every
task has a relation value.

## The Claude Code plugin (convenience path)

The plugin is the same build, delivered as a Claude Code convenience:

```
/plugin marketplace add aniklavida/workforce-os
```

Then run the `workforce-setup` skill. It wraps the same instructions above and
the same `scripts/workforce_setup.py` logic. It is not required. This page is
sufficient on its own.

## Hosts actually tried

| Path / host | What was actually run |
|---|---|
| Plugin build logic (`workforce_setup.py`), no host app | Fixture self-test and acceptance suite. Not a live Notion workspace. |
| This page's literal build steps | Fixture parity proof (`scripts/workforce_install_parity.py`). Not a real agent host. |
| Claude Code plugin as a live install | **Not run.** No clean-install evidence exists. |
| Codex, Cursor, Gemini CLI, any other host | **Not tried.** The instruction is host-agnostic by design, but no non-Claude-Code host has been run against it. |

The phrase "works with any agent" is deliberately not used. Only work actually
run is listed.

## How this instruction is verified

`scripts/workforce_install_parity.py` mechanically follows the literal steps on
this page — an independent build path that reads this page and the structure it
points at — builds a simulated workspace, and diffs it against the workspace the
plugin's build script produces. The two must be identical.

```sh
python3 scripts/workforce_install_parity.py
```

This proves the instruction is self-consistent and complete against the plugin's
own build path. It does **not** prove that a real Codex, Cursor, or Gemini CLI
session, handed this page, follows it correctly. That needs a live
non-Claude-Code agent host; the steps are in the pull request that introduced
this page.

## Finish

Tell the user, in plain language: capture goes to chat, not Notion; they never
fill a field; Domains route work; adding a life area is one Domain option, not a
database. Then create one real task with them, end to end.
