# Architecture

## System boundary

```text
User channels / agent hosts
  Claude Code · Codex · Telegram · Discord · CLI
                    │
         Workforce OS protocol/runtime
  capture · route · permissions · handoff · heartbeat
                    │
          official Notion MCP or API
                    │
             user's Notion workspace
```

Notion remains the storage and visual interface. Official Notion connectivity is consumed rather than rebuilt. Workforce OS owns the opinionated schema, worker contract, routing rules, permission model, heartbeat and host/channel adapters.

## Deliverables

1. **Structure** — idempotent setup and migration for the user's Notion.
2. **Protocol** — public operating rules, worker profiles, skills and commands.
3. **Runtime** — scheduling, channel adapters and heartbeat execution.

## Boundaries

- Core workflow behavior must not depend on one chat platform.
- Host/channel adapters translate input and delivery; they do not own task semantics.
- Notion access follows least privilege and domain scope.
- Secrets remain outside Notion and outside the repository.
- External messages and destructive actions follow explicit approval rules.
- Setup and migration are idempotent and preserve user data.

## Proposed runtime modules

```text
runtime/
  core/          task, worker, handoff and heartbeat rules
  notion/        official MCP/API adapter
  scheduler/     heartbeat scheduling and locking
  channels/      Telegram, Discord and future adapters
  config/        validated local configuration and secret references
  observability/ structured logs and safe diagnostics
```

The runtime language and packaging are not yet decided. A foundation spike will compare deployment simplicity, Notion support, scheduler reliability and cross-platform installation before the choice is fixed.
