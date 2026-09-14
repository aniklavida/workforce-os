---
name: workforce-setup
description: Build the Workforce OS structure in the user's own Notion — one task database, Domains, goals, knowledge, logs and an agent control room. Use when the user wants to set up Workforce OS, build a second brain for their work in Notion, or rebuild the structure. Requires Notion access.
---

# Workforce OS — Setup

Build the structure in the user's **own** Notion. Nothing is copied from anyone else's workspace.

## Before you start

Confirm you have Notion write access. If not, stop and tell the user how to connect it — do not build a partial structure.

Ask where it should live: a new top-level page, or inside an existing one.

## Ask first — five short questions, then build

Do not build a generic workspace and hand it over. Ask these, and build from the answers:

1. **What are the main areas of your life right now?** (Their Domains — expect three to eight. Their words, not yours: "Australia", "my company", "day job".)
2. **What should your assistant call you?**
3. **Where do you want the daily message — right here in this chat, or somewhere else your agent already delivers messages?** Workforce OS has no chat adapter of its own; delivery uses whatever surface the connecting agent already has.
4. **What is the one thing you are actually working toward?** (Becomes their goals page. One line is enough.)
5. **Which agents do you have, or want?** (If they don't know, create only the Assistant.)

If they give short or vague answers, that is expected — **write them up properly yourself.** Never make them fill a form.

## What to create

### The task database — the spine

One database. Everything routes through it.

| Property | Type | Notes |
|---|---|---|
| Task | Title | |
| Status | Status | `Planned` · `In progress` · `Done` — shared by user and agents |
| Assigned To | Select | The user's name + one option per agent |
| Domain | Select | One option per answer to question 1 |
| Priority | Select | `High` · `Medium` · `Low` |
| Type | Select | `Task` · `Ongoing` · `Someday` |
| Start Date | Date | When work may begin |
| Due Date | Date | Final deadline |
| Done When | Text | Completion condition |
| Notes | Text | **User's only.** Describe it that way in the field description |
| Agent Notes | Text | **Agent's only** |
| Done Date | Date | |

Set the field descriptions in Notion. They are how a future agent learns the contract without being told.

**Views:**

- **Today** — not Done, not Someday, sorted by priority then due date
- **My Tasks** — assigned to the user
- **Agent Tasks** — assigned to anyone else
- **One per Domain** — filtered, not Done
- **Board** — grouped by Status
- **Calendar** — by Due Date
- **Someday** — Type is Someday

### Navigation — build it as a gallery, not a list of links

This is what separates a template that looks professional from one that looks improvised.

Create a **Sections** database. Each row **is** an actual section page, so clicking a card opens the real thing rather than a stub. Display it as a **gallery with page covers as the card preview**, grouped by band.

| Property | Type | Purpose |
|---|---|---|
| Section | Title | |
| Group | Select — `Work` / `You` / `Engine` | Groups the gallery into bands |
| Order | Number | Controls card order within a band |
| What it is | Text | The one line shown on the card |

Give every section page a **cover image and an emoji icon**. The cover is the card art; without it the gallery renders as empty grey rectangles and looks worse than a plain list.

A flat list of page links is the default and it reads as unfinished. Cards with art read as a product.

### Pages

```
Home            Today · anything waiting on the user · upcoming · this week
Tasks           the database above
Domains         one child page per Domain from question 1
Goals           from question 4
Knowledge       who they are, how they work, what agents should know
Profile         official records and documents
Logs            daily work log + weekly summaries
Engine Room     AGENTS.md content · one page per agent · outputs
```

**Each Domain page must state which context an agent may load for it.** Without that line, agents read everything and the routing in `AGENTS.md` does not work.

### Off by default

Create these only if asked: habits, finance, health, reading, travel, contacts.

Say this out loud to the user: *starting with everything is why most of these systems die within a month.* Five things they use beats twenty they abandon.

## Build order

Create in this order so nothing is orphaned if it stops halfway:

1. Home page
2. Task database + fields
3. Views
4. Section pages: Domains, Goals, Knowledge, Profile, Reminders, Logs, Engine Room
5. Domain pages
6. Engine Room contents + agent pages
7. Sections database, then move the section pages into it
8. Gallery view, grouped by band
9. Covers and icons on every page
10. Embed the gallery and the live views on Home

**Be resumable.** Before creating anything, check whether it already exists. Re-running setup must never produce duplicates. If something fails, report exactly what was built and what was not — never leave the user guessing.

## Finish

Tell them, in plain language:

- Capture goes to chat, not Notion
- They will never fill a field — the assistant does
- Domains are how work gets routed
- To add a life area, add a Domain option, not a database

Then create one real task with them, end to end, so the first thing they see is it working.

## A note on how it looks

Do not treat this as decoration to add later. A workspace with no covers, no icons and a bare list of page links reads as unfinished, and people abandon things that feel unfinished — regardless of how well the underlying system works.

Covers and icons on every page. Navigation as a gallery. A coloured callout heading each component, because Notion has no borders and callout backgrounds are the only way to make one block read as separate from the next.

Ask the user to pick the cover art themselves if they care about it. Notion's built-in picker takes them ten seconds per page and they get an aesthetic they actually like.
