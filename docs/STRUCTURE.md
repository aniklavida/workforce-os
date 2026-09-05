# Structure

For agents that are not Claude Code: this is what Workforce OS looks like, so you can build or operate it yourself.

## One database

Everything routes through a single task database. There is no second task list anywhere.

| Property | Type | Written by |
|---|---|---|
| Task | Title | agent |
| Status | Status — `Planned` / `In progress` / `Done` | **both** |
| Assigned To | Select — user + one per agent | assistant |
| Domain | Select — one per life area | agent |
| Priority | Select — High / Medium / Low | agent |
| Type | Select — Task / Ongoing / Someday | agent |
| Start Date | Date | agent |
| Due Date | Date | agent |
| Done When | Text | agent |
| Notes | Text | **user only** |
| Agent Notes | Text | **agent only** |
| Done Date | Date | agent |

## Pages

```
Home          today · waiting on you · upcoming · this week
Tasks         the database
Domains       one page per life area
Goals         what this is all for
Knowledge     who the user is, how they work
Profile       official records and documents
Logs          daily work log + weekly summaries
Engine Room   agent rules · one page per agent · outputs
```

## Domains do two jobs

They are how the user navigates, and how an agent decides what to load.

Every Domain page declares its own context — the pages an agent may read when working on a task in that Domain. Without that declaration, agents read everything, which is slower, more expensive and produces worse answers.

Adding a life area means adding one select option. It never means adding a database.

## Why there is no lock field

`Assigned To` routes a task to exactly one agent, and every agent has a distinct role, so two agents cannot compete for the same row. `Status = In progress` is the only signal that work has started.
