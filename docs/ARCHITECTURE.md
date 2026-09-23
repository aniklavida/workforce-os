# Architecture

## System boundary

```text
User channels / agent hosts
  Claude Code · Codex · any other MCP-capable agent
                    │
         Workforce OS protocol (Markdown)
  structure · routing rules · permissions · handoff · review checklist
                    │
   Notion remote MCP (OAuth)  ── one consumer path, no runtime here
                    │
    Notion REST API, data_source_id addressing (2025-09-03)
                    │
             user's Notion workspace
```

Notion remains the storage and visual interface. Official Notion connectivity is consumed rather than rebuilt. Workforce OS owns the opinionated schema, the worker contract, routing rules, the permission model and the content of the review protocol ("heartbeat"). It owns no runtime process, no scheduler and no chat-channel adapter — those are the connecting agent's own capability, not something this project builds or ships.

## Notion connectivity — the one and only consumer path

There is exactly one consumer of Notion connectivity in this project: **whichever coding agent is already running and already has its own Notion access**. At this time the recommended and default path is Notion's **remote MCP server, authenticated with OAuth**. It needs no local JSON server block and no integration token to paste: the user authorizes the remote server in their agent, and the agent speaks to Notion from there. The underlying HTTP API (version `2025-09-03`) is what the MCP wraps; a direct REST client is the fallback, not the default.

There is **no separate heartbeat consumer**. The review protocol is not a process, not a second integration-token credential and not a standalone runtime. It is a checklist plus a silence rule that the already-connected agent runs on its own schedule, using its own Notion access. This is locked in the project architectural decisions (2026-09-15): *"Workforce OS is only a Notion system plus skills... Workforce OS builds no runtime, no bot gateway, no heartbeat scheduler, and no Telegram or Discord adapters."* Any design that introduces a second credential path or a standalone Notion process contradicts that decision and is out of scope.

The remote MCP is the primary path. The local `notion-mcp-server` is being sunset: its own README states that issues and pull requests are not actively monitored. It may exist as a fallback for an environment that cannot use the remote server, but it is not the documented default and nothing here is built against it.

### Data sources, not databases

The 2025-09-03 Notion API made the **data source** the primary abstraction. Database operations address a `data_source_id`, not a `database_id`:

- A task row is created with `parent = { "type": "data_source_id", "data_source_id": "..." }`.
- Rows are read by querying `/v1/data_sources/{data_source_id}/query`.
- A Notion database can now contain multiple data sources; the database is the container, the data source is the table an agent reads and writes.

Every database call in this project addresses a data source going forward. Where older Notion documentation or code says `database_id`, read `data_source_id`. A repo-wide check at the time of writing found no literal `database_id` handle in this repository; the guidance is recorded here and in `docs/STRUCTURE.md` so it does not drift in.

### Batching is a design constraint, not an optimisation

Notion's API allows only a few requests per second (roughly three on average). Every read and write pattern this project documents or ships must therefore paginate and batch:

- Reads use `page_size = 100` (the maximum) and follow `next_cursor` until `has_more` is false.
- Writes batch sibling blocks into a single block-append or page-create request, up to the API limit.
- Nothing fans out one request per row. A view of 200 tasks is at most two paginated reads, not 200.

`scripts/notion_roundtrip_proof.py` implements and measures this; `docs/NOTION_ROUNDTRIP.md` records the observed behaviour.

## The Workforce database and relation-based assignment

The task database's `Assigned To` property is a **relation to a Workforce
database**, one row per worker. It replaces the old hard-coded select (the
user's name plus a fixed trio of agent options). The schema is:

- **Workforce** — `Worker` (title), `Kind` (`Agent`/`Human`), `Role`
  (`Assistant`/`Advisor`/`Specialist`), `Channel` (`Claude Code`/`Codex`/
  `Telegram`/`Discord`/`CLI`/`None`), `Domains` (multi-select), `May approve`
  (checkbox, off by default), `Capabilities` (text), `Status`
  (`Active`/`Paused`). The row's page body is the worker's full startup
  instructions. Every property carries a Notion field description naming who
  writes it.
- **Tasks** — `Assigned To` is a one-way `single_property` relation to
  Workforce. A task points at exactly one worker; nothing is written back onto
  the worker row.

There is no claim field and no lock field. A relation already routes a row to
exactly one worker, and `Status = In progress` on the task is the only "work has
started" signal. Both note fields (`Notes`, the user's, and `Agent Notes`, the
agent's) remain separate and neither role writes the other's.

A **human teammate is an ordinary worker row** with `Kind = Human` and
`Channel = None`. That is the reason the property is a relation rather than a
side effect of one: adding a person later needs no schema change. A worker can
be added entirely from Notion — no repository change — and is then assignable,
because the protocol resolves the relation to the worker row rather than
consulting a hard-coded list.

The schema is encoded twice, deliberately: in prose in
[`skills/workforce-setup/SKILL.md`](../skills/workforce-setup/SKILL.md), which
is what a connected agent executes through Notion MCP, and in executable form
in [`scripts/workforce_schema.py`](../scripts/workforce_schema.py), whose
`--dry-run` prints the exact request payloads and whose `--self-test` proves the
assignment gate.

### The assignment gate — enforced by the protocol, not by Notion

Notion relations do not enforce permissions, so the operating protocol does:

- A worker with empty `Domains` may work in **no** domain. Scope is explicit;
  empty is none, never all.
- A task may only be assigned to a worker whose `Domains` includes the task's
  `Domain`.
- A `Paused` worker receives **no new assignments**. Work already on its queue
  stays until it is reassigned; nothing new lands on it.

`scripts/workforce_schema.py` implements this as `can_assign()`/`assignment_blockers()`
and `--self-test` covers it with fixture workers. The gate is a rule the
Assistant applies before it writes `Assigned To`; it is not a Notion feature.

### Verification status of the Workforce schema

The authoring environment for this change had no live Notion credential, so a
line is drawn here between what was actually exercised and what still needs a
workspace.

| Claim | How it was checked | Status |
|---|---|---|
| Workforce property names, types and option sets | `scripts/workforce_schema.py --dry-run` prints the payloads; asserted in the dry-run report | **Verified locally** |
| Every Workforce property carries a description naming its writer | `--dry-run` reports `property_descriptions_present: true` (payload-level; the API's persistence of descriptions is a separate live row below) | **Verified locally** |
| `Assigned To` is a relation, not a select | `--dry-run` reports `assigned_to_is_relation: true`; setup skill provisions it as a relation | **Verified locally** |
| Empty `Domains` blocks assignment; out-of-scope domain blocks assignment | `scripts/workforce_schema.py --self-test`, 7 fixture cases, 0 failures | **Verified locally** |
| A `Paused` worker receives no new assignment | `--self-test` blocks it; the protocol states the rule | **Verified locally** (gate logic); **not** exercised against a live row |
| A worker added in Notion with no repository change is assignable and read correctly | follows from the relation design; no list of workers exists in the repository to update | **Logic/documentation claim** — needs a live workspace to confirm |
| The Workforce database is created in Notion | not run — no credential here | **NOT YET EXECUTED** |
| The relation and its field descriptions persist and read back | not run — no credential here | **NOT YET EXECUTED** |
| Relation target is configured under `data_source_id` on the 2025-09-03 API | not run — no credential here; older docs use `database_id` | **NOT YET EXECUTED** — confirm on first live run |

Do not read the last three rows as a claim of tested behaviour. The one-command
procedure to complete them is:

```sh
# Fallback REST path, matching the repo's documented one. The primary path is
# still the agent's own Notion MCP/OAuth connection; this script is the
# reference payload and the honest live check.
export NOTION_TOKEN=...                 # never commit this
export NOTION_PARENT_PAGE_ID=...       # the page Workforce OS lives under
python3 scripts/workforce_schema.py --live
# then, to also install the relation on an existing Tasks data source:
python3 scripts/workforce_schema.py --live \
    --tasks-data-source-id <tasks_data_source_id>
```

If `Assigned To` already exists as a select, rename it to `Assigned To (legacy)`
first — Notion cannot change a property's type in place. With the relation
installed, add a worker directly in Notion, assign a task to it, and confirm the
relation resolves; that settles the remaining live rows above.

## Idempotent setup orchestration

Workforce OS builds its entire Notion structure from five answers:
1. Main areas of life or work (Domains)
2. What the assistant should call the user
3. Where the daily message goes (chat channel)
4. The one primary goal the user is working toward
5. Which workers they have or want

### Core principles of setup

- **Workforce OS marker discovery:** Before creating any database or page, setup searches the parent page for a Workforce OS marker (`[workforce-os:root]`) or existing child databases and pages (`Workforce`, `Tasks`, `Domains`, etc.).
- **Zero-duplicate reconciliation:** If a marker or existing structure is found, setup reconciles rather than recreates. Missing properties, select options, and views are added to existing objects; databases and pages are never duplicated.
- **Preview and progress reporting:** Setup previews all planned additions and reconciliations prior to execution, and reports progress per object created.
- **Confirmation for destructive actions:** Every destructive or overwriting step (such as archiving legacy properties or modifying existing pages) requires explicit confirmation.
- **Documented build order:** Objects are created in a strict, documented sequence so nothing is orphaned if setup stops halfway:
  1. Marker block
  2. Workforce database (8 properties + descriptions)
  3. Worker rows (User + Assistant + Specialists)
  4. Tasks database (with `Assigned To` relation → Workforce)
  5. Tasks views (Today, My Tasks, Agent Tasks, one per Domain, Board, Calendar, Someday)
  6. Section pages (Domains, Goals, Knowledge, Profile, Logs)
  7. Domain subpages under Domains, each declaring mandatory agent read scope
  8. Worker startup briefs in Workforce row bodies
  9. Initial real task end-to-end
- **Failure recovery and resumability:** On failure, setup reports exactly what was built and what was not built. Because setup is idempotent, re-running on the same parent page discovers existing objects, reconciles without duplicate creation, and resumes from the interruption point.
- **Mandatory Domain context routing:** Each Domain page declares which pages an agent may read for that Domain. Without this declaration, agents read everything and the routing in `AGENTS.md` does not work.
- **Off-by-default scope:** Habits, finance, health, reading, travel, and contacts are off by default. Starting with everything is documented as the reason personal operating systems die within a month. Day one is five things the user will actually use, not twenty they will abandon. A life area is one select option, never a new database.

### Verification status of idempotent setup

The setup logic is implemented and tested in `scripts/workforce_setup.py`.

| Claim | How it was checked | Status |
|---|---|---|
| Fresh setup generates complete structure plan from 5 answers | `scripts/workforce_setup.py --self-test` (Test 1) and `--dry-run` | **Verified locally** |
| Every Domain page declares mandatory agent read context | `scripts/workforce_setup.py --self-test` asserts AGENTS.md routing contract block on domain pages | **Verified locally** |
| Re-running against existing marker produces zero duplicate creates | `scripts/workforce_setup.py --self-test` (Test 2 & 2b) asserts 0 duplicate databases and 0 duplicate pages | **Verified locally** |
| Resumption after mid-setup failure completes without duplicating objects | `scripts/workforce_setup.py --self-test` (Test 3) injects mid-setup failure, verifies report, and asserts 0 duplicate DBs on resume | **Verified locally** |
| Off-by-default scope and rationale reported | asserted in dry-run report output | **Verified locally** |
| Full setup against a live Notion workspace | not run — no credential in this environment | **NOT YET EXECUTED** |
| Live Notion view creation via REST API | not run — no credential in this environment | **NOT YET EXECUTED** |

Do not read the last two rows as a claim of tested behaviour. The one-command
procedure to complete them is:

```sh
# Fallback REST path. The primary path is the agent's own Notion MCP/OAuth connection;
# this script provides the honest executable check.
export NOTION_TOKEN=...                 # never commit this
export NOTION_PARENT_PAGE_ID=...        # the page Workforce OS lives under
python3 scripts/workforce_setup.py --live
```

### Verification status of select-to-relation migration

The migration logic from legacy select-based `Assigned To` to the relation-based Workforce model is implemented and tested in `scripts/workforce_migration.py`.

| Claim | How it was checked | Status |
|---|---|---|
| Only `Assigned To` changes on any task; `Notes` and `Agent Notes` preserved byte for byte | `scripts/workforce_migration.py --self-test` (Test 1), asserted row-by-row across fixture tasks | **Verified locally** |
| Existing select options map to Workforce rows; human user mapped to `Kind = Human` and `Channel = None` | `--self-test` (Test 1), asserted worker rows in Workforce DB | **Verified locally** |
| Unmatched values reported by name, never silently dropped, and never guessed at | `--self-test` (Test 1b), asserted task left untouched on legacy property and reported | **Verified locally** |
| Re-running migration against an already-migrated workspace is a zero-change no-op | `--self-test` (Test 2), asserted 0 tasks migrated, 0 duplicate workers, 0 property diffs | **Verified locally** |
| Resumption after mid-migration interruption reaches identical end state as uninterrupted run | `--self-test` (Test 3), asserted matching workers and task properties across interrupted vs control workspaces | **Verified locally** |
| Pre-migration values logged for reversal and rollback restores original state | `--self-test` (Test 1), asserted rollback restores pre-migration properties | **Verified locally** |
| Migration executed against a live Notion workspace | not run — no credential in this environment | **NOT YET EXECUTED** |

Do not read the last row as a claim of tested behaviour. The one-command procedure to complete it is:

```sh
# Fallback REST path. The primary path is the agent's own Notion MCP/OAuth connection;
# this script provides the honest executable check.
export NOTION_TOKEN=...                 # never commit this
export NOTION_PARENT_PAGE_ID=...        # the page Workforce OS lives under
python3 scripts/workforce_migration.py --live \
    --tasks-data-source-id <tasks_data_source_id>
```

## Deliverables

1. **Structure** — idempotent setup and migration for the user's Notion.
2. **Protocol** — public operating rules, worker profiles, skills and commands, written as portable Markdown intended for any agent that can read files and reach Notion over MCP (Claude Code is the only tested path today; other agent paths are planned).

There is no third deliverable. Earlier drafts of this document described a runtime, scheduler and channel-adapter layer; that layer is permanently out of scope. Scheduling and chat delivery belong to whichever agent the user connects.

## How the review protocol ("heartbeat") actually runs

Workforce OS defines what a review checks (overdue, due-soon, stalled, waiting-on-user, recent completions) and when it should stay silent. It does **not** define how or when that check is triggered. In practice:

- Claude Code can run the review on a schedule it manages itself (for example, a scheduled task the user sets up), then execute the `workforce-operate` skill against the checklist.
- Codex or any other MCP-capable agent is planned to do the same using its own scheduling mechanism and `AGENTS.md` (unverified today).
- Delivery goes through whatever chat surface that agent already has — there is no Workforce OS-specific channel code to install.

## Boundaries

- Core workflow behavior (capture, assignment, handoff, review content) must not depend on one agent host or chat platform.
- Notion access follows least privilege and domain scope.
- Secrets stay outside Notion and outside the repository.
- External messages and destructive actions follow explicit approval rules.
- Setup and migration are idempotent and preserve user data.
- Workforce OS never assumes it is the process invoking itself — it is always read and executed by an agent that was invoked some other way.
