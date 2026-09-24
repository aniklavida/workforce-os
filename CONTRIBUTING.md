# Contributing

Thanks for looking. This project is small on purpose, so the most useful contributions are usually subtractions — or well-scoped specialists.

## The one principle

**The user never fills a field.**

Every proposal gets measured against that. If a change means the user has to maintain something by hand, tag something, or keep a tracker current, it does not belong here — no matter how good the feature is. That burden is the documented reason these systems get abandoned, and removing it is the entire product.

## What is genuinely wanted

- **Contributed specialist worker profiles.** The project grows by adding specialists (single-file, single-concern), not by adding databases or modules. A well-written specialist profile for a real, narrow job is the highest-value contribution anyone can make.
- Making the protocol clearer or shorter
- Setup reliability — resumability, better handling of partial failure
- Support for other agent tools
- Fixing anything that tells an agent to guess

## What is usually declined

- **New databases.** A life area is a Domain option, not a database.
- **Modules that are on by default.** Day one stays at five things.
- **Anything that reintroduces manual upkeep.** If a change means the user has to maintain something by hand, it does not belong here.
- **Per-tool instruction files.** `AGENTS.md` is the source; other files point at it.
- **Vague, multi-role specialists.** A specialist that attempts to manage tasks, advise on strategy, and execute deliverables all at once behaves like a worse assistant and breaks role separation.

## Contributing a specialist worker profile

The primary path for extending Workforce OS is contributing a specialist profile.

### Locked design decisions

1. **The project grows by adding specialists, not by adding databases or modules.** Never propose a new database or tracking module to support a workflow. Add a specialist worker profile instead.
2. **A contributed specialist is always a single file with a single concern.** Every specialist lives in its own file under `agents/specialists/<name>.md`.
3. **The user never fills a field.** A specialist must execute deliverables directly into the task page body and update `Agent Notes`, never demanding manual property maintenance from the user.
4. **Sharp remit.** A specialist with a vague remit behaves like a worse assistant. Profiles must explicitly define what they do, what they do not do, and what requires approval.

### How to add a specialist (copy one file, edit one section)

1. **Copy the template:** Copy `agents/workforce-specialist.md` (or the worked example in `agents/specialists/researcher.md`) to `agents/specialists/<name>.md`.
2. **Update frontmatter:** Set `name: workforce-<name>` and a concise `description` naming the specific deliverable and trigger.
3. **Edit the `## Scope` section:** Replace the scope block with explicit, concrete statements:
   - `**I do:**` The single kind of work this specialist owns.
   - `**I do not:**` Adjacent responsibilities belonging to Assistant (coordinating/scheduling), Advisor (evaluating/strategy), or other specialists (e.g. writing vs coding vs research).
   - `**Approval required for:**` External messages, payments/charges, publishing, or marking Done when the brief mandates user verification.
4. **Verify mechanically:** Run the specialist verification suite:
   ```bash
   python3 scripts/workforce_specialist.py --self-test
   ```
   Ensure the test suite passes cleanly with zero failures.

## Making a change

1. Open an issue first for anything beyond a typo — it saves you writing something that gets declined.
2. Keep pull requests to one concern.
3. Update `CHANGELOG.md` under `## [Unreleased]`.
4. Do not bump the version in `plugin.json`; that happens at release.

## Releasing

Maintainers only:

1. Move `Unreleased` entries into a new version section in `CHANGELOG.md`.
2. Set the same version in `.claude-plugin/plugin.json`.
3. Tag `vX.Y.Z` and push. CI checks the tag matches and publishes the release.

CI will fail if the tag and `plugin.json` disagree, so the two cannot drift.

## Never commit

Notion tokens, bot tokens, or Notion exports containing personal data. `.gitignore` covers the usual paths and CI scans for credential patterns, but neither is a substitute for checking your own diff.
