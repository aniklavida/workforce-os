# Workforce OS

**The Ultimate Agent Workforce — a Notion life OS your agents actually run.**

Most Notion life OS templates die within a month. Not because they are badly designed, but because *you* have to maintain them. Every database needs updating, every property needs filling. You fall behind once, and the system becomes a monument to falling behind.

Workforce OS fixes the cause instead of adding more modules: **the agents do the maintenance.**

You send one messy line to your assistant on Telegram or Discord. It writes the proper task — next action, domain, dates, priority — into Notion. Then it tells you what matters, once a day. You never fill a field.

---

## What makes it different

| Every other life OS | Workforce OS |
|---|---|
| You fill the fields | An agent fills them from your rough message |
| Dies when you stop maintaining it | Nothing to maintain |
| No reason to come back | Your assistant messages you daily |
| One database per life area → 17 dead modules | One task database, **Domains** as options |
| Built for an idealised version of you | Built for someone who types three words and moves on |

## The core idea: Domains

Other templates get "complete" by adding a database for every area of life — health, finance, travel, reading, career. You end up maintaining twelve systems.

Here, a life area is **one option in one field**. Adding *Health* to your life costs nothing. That is why this can cover everything and still stay small.

Domains do double duty: they are how you navigate, and how an agent knows which context to load. A task tagged `Australia` means the agent reads the Australia page and your documents — not your whole workspace.

## Roles, not one big assistant

Three kinds of agent, deliberately separated:

- **Assistant** — captures, organises, assigns, monitors, reminds. Never does the work itself.
- **Advisor** — checks whether the plan is still right. Researches. Stays silent unless it found something worth saying.
- **Specialists** — actually do assigned work and hand back output for approval.

Collapse these into one agent and it becomes a to-do list with extra steps.

## Works with any agent

The operating protocol lives in [`AGENTS.md`](AGENTS.md) — the [cross-tool open standard](https://agents.md/) backed by OpenAI, Google, Cursor, Factory and Sourcegraph. Claude, ChatGPT, Gemini, Cursor and self-hosted agents all read the same file.

Claude Code additionally gets a one-command install and two skills.

## Install

**Claude Code**

```
/plugin marketplace add <owner>/workforce-os
/plugin install workforce-os
```

Then run the setup skill. It asks a few short questions and builds the structure in your own Notion — nothing is copied from anyone else's workspace.

**Any other agent**

Point it at `AGENTS.md` and `docs/STRUCTURE.md`, and connect it to Notion.

## Requirements

- A Notion account
- Notion access for your agent (MCP or API)
- Optional: Telegram or Discord, if you want the daily message

## Start small on purpose

Day one turns on five things: **Tasks · Domains · Today · Reminders · Goals.**

Habits, finance, health, reading, travel and contacts exist but stay off until you actually want them. This is deliberate — completeness on day one is what kills these systems.

## Licence

MIT. See [LICENSE](LICENSE).
