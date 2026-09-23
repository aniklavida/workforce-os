---
description: Route ready work to the right agent, or flag that no specialist exists for it
argument-hint: [task name or "all"]
---

Assign work: **$ARGUMENTS**

Follow `AGENTS.md`.

1. Confirm the task is actually ready — next action, done-condition and domain are known. If not, it is not assignable yet; ask what is missing.
2. Decide who does it: a `Kind = Human` worker, or a specialist.
3. Check the assignment gate: the worker is `Active`, its `Domains` include the task's `Domain`, and `Domains` is not empty. Empty means none. If assignment is blocked, state why in one clear line. If the task involves the sensitive `Profile` domain, confirm the worker has an explicit, loggable grant.
4. Set the `Assigned To` relation to that one Workforce row.

**If the work needs a specialist that does not exist, say so plainly and offer to add a Worker row.** Adding one from Notion needs no repository change. Do not assign it to the assistant. Do not quietly do it yourself.

With no argument, review everything unassigned.
