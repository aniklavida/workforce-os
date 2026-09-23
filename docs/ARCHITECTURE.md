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

There is **no separate heartbeat consumer**. The review protocol is not a process, not a second integration-token credential and not a standalone runtime. It is a checklist plus a silence rule that the already-connected agent runs on its own schedule, using its own Notion access. This is locked in the project decision log (`_ai/Workforce-OS/DECISIONS.md`, 2026-09-15): *"Workforce OS is only a Notion system plus skills... Workforce OS builds no runtime, no bot gateway, no heartbeat scheduler, and no Telegram or Discord adapters."* Any design that introduces a second credential path or a standalone Notion process contradicts that decision and is out of scope.

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
