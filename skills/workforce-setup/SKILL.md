---
name: workforce-setup
description: Build the Workforce OS structure in the user's own Notion — a task database relation-linked to a Workforce database of worker profiles, plus Domains, goals, knowledge and logs. Use when the user wants to set up Workforce OS, build a second brain for their work in Notion, or rebuild the structure. Requires Notion access.
---

# Workforce OS — Setup

Build the structure in the user's **own** Notion. Nothing is copied from anyone else's workspace.

## Before you start

Confirm you have Notion write access. If not, stop and tell the user how to connect it — do not build a partial structure.

Ask where it should live: a new top-level page, or inside an existing one.

### Idempotency and the Workforce OS marker

Before creating anything, **search the parent page for a Workforce OS marker** (`[workforce-os:root]`) or existing child databases and pages (`Workforce`, `Tasks`, `Domains`, etc.):

- **If found:** Reconcile rather than recreate. Add missing properties, options, and views to what already exists. Never create a duplicate database or duplicate page.
- **If fresh:** Create the marker callout block on the parent page and proceed with fresh setup in the documented build order.
- **Preview before creating:** Present a preview of what will be created and what will be reconciled, and report progress per object created.
- **Destructive confirmation:** Every destructive or overwriting step (such as archiving a legacy property or replacing page content) requires explicit confirmation first.

## Ask first — five short questions, then build

Do not build a generic workspace and hand it over. Ask these, and build from the answers:

1. **What are the main areas of your life right now?** (Their Domains — expect three to eight. Their words, not yours: "Australia", "my company", "day job".)
2. **What should your assistant call you?**
3. **Where do you want the daily message — right here in this chat, or somewhere else your agent already delivers messages?** Workforce OS has no chat adapter of its own; delivery uses whatever surface the connecting agent already has.
4. **What is the one thing you are actually working toward?** (Becomes their goals page. One line is enough.)
5. **Which workers they have, or want?** (If they don't know, create only the Assistant.) Each becomes a Worker row — role, channel, domains, capabilities.

If they give short or vague answers, that is expected — **write them up properly yourself.** Never make them fill a form.

### Decisions locked

- Day one is five things the user will use, not twenty they will abandon.
- A life area is one select option, never a new database.

### Off by default

Create these only if asked: habits, finance, health, reading, travel, contacts.

Say this out loud to the user: *starting with everything is documented as the reason these systems die within a month. Day one is five things you will actually use, not twenty you will abandon. Adding a life area later is just adding a single select option, never a new database.*

## What to create

### The task database — the spine

One database. Everything routes through it.

When you read or write it through the API or MCP, address its **data source**,
not the database. The 2025-09-03 Notion API made `data_source` the primary
abstraction: rows are created with `parent.type = "data_source_id"` and read
through `/v1/data_sources/{data_source_id}/query`. `database_id` is the old
handle and is wrong for row operations. The user still sees a normal database;
only the API handle changes.

| Property | Type | Notes |
|---|---|---|
| Task | Title | Agent. Short, clear action or outcome |
| Status | Status | `Planned` · `In progress` · `Done` — shared by user and agents |
| Assigned To | Relation → Workforce | Exactly one worker per task. Never a select |
| Domain | Select | One option per answer to question 1 |
| Priority | Select | `High` · `Medium` · `Low` |
| Type | Select | `Task` · `Ongoing` · `Someday` |
| Start Date | Date | When work may begin |
| Due Date | Date | Final deadline |
| Done When | Text | Completion condition |
| Notes | Text | **User's only.** Describe it that way in the field description |
| Agent Notes | Text | **Agent's only** |
| Done Date | Date | Completion timestamp |

Set the field descriptions in Notion. They are how a future agent learns the contract without being told.

**Views:**

- **Today** — not Done, not Someday, sorted by priority then due date
- **My Tasks** — `Assigned To` relation points at a worker with `Kind = Human`
- **Agent Tasks** — `Assigned To` relation points at a worker with `Kind = Agent`
- **One per Domain** — filtered by `Domain`, not Done
- **Board** — grouped by Status (`Planned`, `In progress`, `Done`)
- **Calendar** — grouped by Due Date
- **Someday** — Type is Someday

### The Workforce database — one row per worker

This is the database the old `Engine Room` page became. Every worker the user
can assign to is a row here: agents and people alike. **`Assigned To` on Tasks
is a relation to this database**, so an assignment resolves to a real profile —
role, channel, permissions, domain scope — not to a bare label.

| Property | Type | Options / notes | Written by |
|---|---|---|---|
| Worker | Title | The display name; what `Assigned To` points at | Assistant |
| Kind | Select | `Agent` · `Human` | Assistant |
| Role | Select | `Assistant` · `Advisor` · `Specialist` | Assistant |
| Channel | Select | `Claude Code` · `Codex` · `Telegram` · `Discord` · `CLI` · `None` | Assistant |
| Domains | Multi-select | Domains this worker may work in. **Empty means none** | Assistant |
| May approve | Checkbox | Off by default. On = may approve its own output | Assistant |
| Capabilities | Text | Plain language: what it does and does not do | Assistant |
| Status | Select | `Active` · `Paused` | **Both** |

The **ninth** item is not a property: the **page body of each row is the full
instructions that worker reads at startup.** Put the worker's operating
brief there.

**Every property carries a Notion field description naming who writes it.**
That is how a future agent learns the contract without being told out of band.
Write the descriptions from the table above.

**A human teammate is just a worker row** with `Kind = Human` and
`Channel = None`. Adding one requires no schema change and no repository
change — that is the whole point of a relation over a fixed select.

**A user can add a worker entirely from Notion.** Create a row, fill the
properties, write the instructions in the page body — nothing in this
repository has to change for that worker to be assignable. The protocol reads
the row, not a hard-coded list.

**Create the Workforce database before the Tasks `Assigned To` relation.** A
relation needs its target to exist first. If Tasks already exists with a select
called `Assigned To`, see *Migrating an existing select* below.

### Domain scope and the assignment gate

`Domains` and `Status` are not decoration; the operating protocol enforces them
before it writes an assignment:

- **Empty `Domains` means none**, not all. A worker with no domains may not
  load context for, or act on, any domain. Grant scope explicitly.
- **A `Paused` worker receives no new assignments.** It keeps the work already
  on its queue until that is reassigned; nothing new lands on it.
- A task may only be assigned to a worker whose `Domains` includes the task's
  `Domain`. The Assistant applies this gate at assignment time — Notion does
  not enforce it for you.

`scripts/workforce_schema.py` encodes this gate as `can_assign()` and proves it
with fixture workers via `--self-test`.

### Migrating an existing select

Notion cannot change a property's type in place, so a workspace that already
has `Assigned To` as a select migrates in four steps, preserving rows:

1. Rename the existing select to `Assigned To (legacy)`.
2. Create the Worker rows in the new Workforce database — one per select
   option, plus a row for the user (`Kind = Human`, `Channel = None`).
3. Add `Assigned To` as a Relation → Workforce, then move each task's value
   across by matching the old option name to the worker row.
4. Confirm every task has a relation value, then delete
   `Assigned To (legacy)`.

Never delete the legacy property before step 4. If a row cannot be matched,
leave it on the legacy property and report it — do not invent a worker.

### Pages

```
Home            Today · anything waiting on the user · upcoming · this week
Tasks           the database above
Workforce       the worker database above · one row per worker · instructions in row body
Domains         parent page with one child page per Domain from question 1
Goals           from question 4
Knowledge       who they are, how they work, what agents should know
Profile         official records and documents
Logs            daily work log + weekly summaries
```

### Required Domain context declaration

**Each Domain page must declare which context an agent may load for it.**
Without that line, agents read everything and the routing in `AGENTS.md` does not work.
Make this a required part of Domain creation, not optional.

On each domain page (`Domains/<Domain Name>`), include this callout block and context declaration:

```markdown
> 🛡️ **AGENT ROUTING CONTRACT (AGENTS.md rule 5):** An agent working in the '<Domain Name>' domain may ONLY read this domain page, its declared children, and domain-relevant entries in Goals and Knowledge. Loading unlisted domains or the Profile page is strictly prohibited.

## Declared Context for this Domain
- This Domain page (Domains/<Domain Name>) and its immediate children
- Goals relevant to <Domain Name>
- Knowledge base entries tagged for <Domain Name>
```

### Navigation — build it as a gallery, not a list of links

This is what separates a template that looks professional from one that looks improvised.

Create a **Sections** database. Each row **is** an actual section page, so clicking a gallery item opens the real thing rather than a stub. Display it as a **gallery with page covers as the gallery preview**, grouped by band.

| Property | Type | Purpose |
|---|---|---|
| Section | Title | |
| Group | Select — `Work` / `You` / `Engine` | Groups the gallery into bands |
| Order | Number | Controls item order within a band |
| What it is | Text | The one line shown on each item |

Give every section page a **cover image and an emoji icon**. The cover provides visual art; without it the gallery renders as empty grey rectangles and looks worse than a plain list.

## Build order

Create in this order so nothing is orphaned if it stops halfway:

1. **Marker block** on parent page (`[workforce-os:root]`)
2. **Workforce database** + all eight properties + field descriptions + a `Kind = Human`, `Channel = None` row for the user (question 2) + worker rows per answer to question 5
3. **Task database** + fields, with `Assigned To` as a Relation → Workforce
4. **Views** on Tasks (Today, My Tasks, Agent Tasks, one per Domain, Board, Calendar, Someday)
5. **Section pages**: Domains, Goals, Knowledge, Profile, Logs
6. **Domain pages** under Domains, each with mandatory declared agent read context
7. **Worker instructions** written into each Workforce row body
8. **Sections database** and gallery navigation view
9. **First real task** created end to end with the user

The Workforce database comes before Tasks: a relation cannot point at a target
that does not exist yet.

### Resumability and failure handling

Before creating anything, check whether it already exists. Re-running setup must
never produce duplicates.

If setup fails or access is lost mid-run, report:
- **What was built:** Exact list of objects created before the interruption.
- **What was NOT built:** Exact list of pending objects.

Subsequent execution resumes from the interruption point. Existing databases and
pages are discovered and reconciled rather than recreated.

## Finish

Tell them, in plain language:

- Capture goes to chat, not Notion
- They will never fill a field — the assistant does
- Domains are how work gets routed
- To add a life area, add a Domain option, not a database

Then create one real task with them, end to end, so the first thing they see is it working.

## Executable setup and verification

The setup logic is encoded and tested in `scripts/workforce_setup.py`:

```sh
# Dry run: previews the plan and validates structure generation without credentials
python3 scripts/workforce_setup.py --dry-run

# Self-test: runs automated tests for fresh setup, idempotency (0 duplicates), and failure recovery
python3 scripts/workforce_setup.py --self-test

# Live run: executes setup against Notion REST API
NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... \
    python3 scripts/workforce_setup.py --live
```
