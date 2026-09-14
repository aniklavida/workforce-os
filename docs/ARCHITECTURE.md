# Architecture

## System boundary

```text
User channels / agent hosts
  Claude Code · Codex · any other MCP-capable agent
                    │
         Workforce OS protocol (Markdown)
  structure · routing rules · permissions · handoff · review checklist
                    │
          official Notion MCP or API
                    │
             user's Notion workspace
```

Notion remains the storage and visual interface. Official Notion connectivity is consumed rather than rebuilt. Workforce OS owns the opinionated schema, the worker contract, routing rules, the permission model and the content of the review protocol ("heartbeat"). It owns no runtime process, no scheduler and no chat-channel adapter — those are the connecting agent's own capability, not something this project builds or ships.

## Deliverables

1. **Structure** — idempotent setup and migration for the user's Notion.
2. **Protocol** — public operating rules, worker profiles, skills and commands, written as portable Markdown so any agent that can read files and reach Notion over MCP can execute them.

There is no third deliverable. Earlier drafts of this document described a runtime, scheduler and channel-adapter layer; that layer is permanently out of scope. Scheduling and chat delivery belong to whichever agent the user connects.

## How the review protocol ("heartbeat") actually runs

Workforce OS defines what a review checks (overdue, due-soon, stalled, waiting-on-user, recent completions) and when it should stay silent. It does **not** define how or when that check is triggered. In practice:

- Claude Code can run the review on a schedule it manages itself (for example, a scheduled task the user sets up), then execute the `workforce-operate` skill against the checklist.
- Codex or any other MCP-capable agent can do the same using its own scheduling mechanism and `AGENTS.md`.
- Delivery goes through whatever chat surface that agent already has — there is no Workforce OS-specific channel code to install.

## Boundaries

- Core workflow behavior (capture, assignment, handoff, review content) must not depend on one agent host or chat platform.
- Notion access follows least privilege and domain scope.
- Secrets stay outside Notion and outside the repository.
- External messages and destructive actions follow explicit approval rules.
- Setup and migration are idempotent and preserve user data.
- Workforce OS never assumes it is the process invoking itself — it is always read and executed by an agent that was invoked some other way.
