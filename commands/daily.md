---
description: The daily status message — what is due, stuck, moving, and suspiciously empty
---

Produce today's status. Follow `AGENTS.md` section 8 and `scripts/workforce_heartbeat.py`.

The review protocol evaluates six deterministic locked rules against the workspace state:

1. **Due today, or overdue:** Tasks whose Due Date is on or before today and not Done.
2. **Due in the next two days:** Tasks due within the next two calendar days and not Done.
3. **Sitting `In progress` longer than expected:** Tasks in progress beyond expected threshold (3+ days) or stalled in agent notes.
4. **Waiting on the user's answer:** Tasks in progress blocked on user clarification or approval.
5. **Finished since yesterday:** Tasks completed today or yesterday.
6. **Any day ahead that is suspiciously empty:** An upcoming scheduled day with zero planned items (raised unprompted — silence about a planning gap is a bug).

**Output format and constraints:**
- Send in chat, never in Notion.
- Write **three to five lines** when items qualify (or fewer if few qualify).
- Reduce pressure, do not add it — **never paste the backlog** (summarize counts rather than dumping long lists; capped at five lines maximum).

**Silence rule:**
- Silence is a first-class outcome, not an accident.
- If there is genuinely nothing qualifying across all six rules, stay completely silent (zero lines). Never pad or send weak observations on schedule.
