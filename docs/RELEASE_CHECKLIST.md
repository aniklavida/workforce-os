# Version 1.0 release checklist

## Truth and product

- [ ] Notion, local spec, README and implementation agree.
- [ ] Every public claim has working evidence or is clearly labelled planned.
- [ ] Positioning consistently describes workforce coordination rather than a generic life OS.

## Setup and operation

- [ ] Fresh setup and repeated setup pass without duplication.
- [ ] Migration preserves existing tasks and user-authored notes.
- [ ] Multi-worker assignment, permissions and handoff work end to end.
- [ ] The review protocol's checklist and silence behavior are verified against fixture data (scheduling and delivery are the connecting agent's own capability, not tested here).
- [ ] Claude Code installation passes fresh-environment tests; the Codex `AGENTS.md` path is documented and tested where feasible.
- [ ] Disconnect/uninstall removes access without deleting user data.

## Repository

- [ ] README, spec, architecture, roadmap and troubleshooting are complete.
- [ ] SECURITY.md, CODE_OF_CONDUCT.md and contributor instructions are complete.
- [ ] GitHub description, topics and homepage are set.
- [ ] Third-party licences, commits and required attribution are recorded.
- [ ] CI and release workflows pass.
- [ ] Repository is clean and local HEAD equals the intended remote commit.

## Launch

- [ ] A 60–90 second demo proves capture, routing, handoff and the review protocol.
- [ ] Release notes and changelog are accurate.
- [ ] Tag and public release are created only after all blockers pass.
