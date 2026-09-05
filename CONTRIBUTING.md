# Contributing

Thanks for looking. This project is small on purpose, so the most useful contributions are usually subtractions.

## The one principle

**The user never fills a field.**

Every proposal gets measured against that. If a change means the user has to maintain something by hand, tag something, or keep a tracker current, it does not belong here — no matter how good the feature is. That burden is the documented reason these systems get abandoned, and removing it is the entire product.

## What is genuinely wanted

- Making the protocol clearer or shorter
- Specialist agent definitions for real jobs
- Setup reliability — resumability, better handling of partial failure
- Support for other agent tools
- Fixing anything that tells an agent to guess

## What is usually declined

- New databases. A life area is a Domain option, not a database.
- Modules that are on by default. Day one stays at five things.
- Anything that reintroduces manual upkeep.
- Per-tool instruction files. `AGENTS.md` is the source; other files point at it.

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
