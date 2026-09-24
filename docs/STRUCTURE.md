# Structure

For agents that are not Claude Code (planned, unverified): this is what Workforce OS looks like, so you can build or operate it yourself. The pasteable install instruction is in [`INSTALL.md`](INSTALL.md); it points here rather than copying this page. No host other than Claude Code has been tried — see *Hosts actually tried* in `INSTALL.md`.

> **API addressing.** The 2025-09-03 Notion API makes the **data source** the
> primary abstraction. When you read or write rows through the API or MCP, you
> address the task **`data_source_id`**, not the `database_id`. A row is created
> with `parent.type = "data_source_id"`, and rows are read by querying
> `/v1/data_sources/{data_source_id}/query`. "Database" below means the Notion
> container the user sees; the agent's handle on it is the data source.

## The task database

Everything routes through a single task database. There is no second task list anywhere.

| Property | Type | Written by |
|---|---|---|
| Task | Title | agent |
| Status | Status — `Planned` / `In progress` / `Done` | **both** |
| Assigned To | **Relation → Workforce** — exactly one worker | assistant |
| Domain | Select — one per life area | agent |
| Priority | Select — High / Medium / Low | agent |
| Type | Select — Task / Ongoing / Someday | agent |
| Start Date | Date | agent |
| Due Date | Date | agent |
| Done When | Text | agent |
| Notes | Text | **user only** |
| Agent Notes | Text | **agent only** |
| Done Date | Date | agent |

### Views

- **Today** — not Done, not Someday, sorted by Priority then Due Date
- **My Tasks** — `Assigned To` relation points at a worker with `Kind = Human`
- **Agent Tasks** — `Assigned To` relation points at a worker with `Kind = Agent`
- **One per Domain** — filtered by `Domain`, not Done
- **Board** — grouped by Status (`Planned`, `In progress`, `Done`)
- **Calendar** — grouped by Due Date
- **Someday** — Type is Someday

## The Workforce database — one row per worker

The old `Engine Room` page is now a database. Every assignable worker is a row,
agent or human. `Assigned To` is a relation to this database, so an assignment
resolves to a profile (role, channel, permissions, domain scope) instead of a
bare select label.

| Property | Type | Written by |
|---|---|---|
| Worker | Title — the display name `Assigned To` points at | assistant |
| Kind | Select — `Agent` / `Human` | assistant |
| Role | Select — `Assistant` / `Advisor` / `Specialist` | assistant |
| Channel | Select — `Claude Code` / `Codex` / `Telegram` / `Discord` / `CLI` / `None` | assistant |
| Domains | Multi-select — **empty means none** | assistant |
| May approve | Checkbox — off by default | assistant |
| Capabilities | Text — what it does and does not do | assistant |
| Status | Select — `Active` / `Paused` | **both** |

The page body of each row holds the worker's full startup instructions. Every
property carries a Notion field description naming who writes it.

A human teammate is a row with `Kind = Human` and `Channel = None`. A worker
added directly in Notion — no repository change — is assignable and read
correctly, because the protocol resolves `Assigned To` through the relation.

### The assignment gate

- A worker with empty `Domains` may work in no domain. Scope is explicit.
- A `Paused` worker receives no new assignments.
- A task may only be assigned to a worker whose `Domains` includes the task's
  `Domain`.

The Assistant applies this at assignment time. Notion does not enforce it.
`scripts/workforce_schema.py --self-test` proves the gate on fixture workers.

See [`ARCHITECTURE.md`](ARCHITECTURE.md#verification-status-of-the-workforce-schema)
for what has been verified locally versus what still needs a live workspace.

## Pages

```
Home          today · waiting on you · upcoming · this week
Tasks         the task database
Workforce     worker profiles · role, channel, permissions, instructions
Domains       one page per life area
Goals         what this is all for
Knowledge     who the user is, how they work
Profile       official records and documents
Logs          daily work log + weekly summaries
```

The parent page carries the Workforce OS marker (`[workforce-os:root]`). Setup is idempotent: re-running setup discovers existing objects and reconciles missing properties and views without creating duplicate databases or pages.

## Domains do two jobs

They are how the user navigates, and how an agent decides what to load.

Every Domain page declares its own context — the pages an agent may read when working on a task in that Domain. Without that declaration, agents read everything, which is slower, more expensive and produces worse answers.

Adding a life area means adding one select option. It never means adding a database.

## Why there is no lock field

`Assigned To` routes a task to exactly one worker — the relation points at one Workforce row — and every worker has a distinct role, so two workers cannot compete for the same row. `Status = In progress` is the only signal that work has started.
