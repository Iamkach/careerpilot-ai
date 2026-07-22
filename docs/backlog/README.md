# Backlog — remaining work

Steps 0-1, 2-6, 8, 9 (plus both quick-fixes' first item) are implemented and retired — see
[`../CHANGELOG.md`](../CHANGELOG.md) for what shipped and [`../TODO.md`](../TODO.md) for the
small gaps each left behind (a missing `encoding="utf-8"`, an unlogged bare `except`, two unrun
manual QA checks — the handful of gaps Step 9's test suite had characterized as not-yet-fixed
are now fixed, see `../TODO.md`).

Open stories:

| Story | What it does | Depends on | Size |
|---|---|---|---|
| [step-7-communications-subsystem.md](step-7-communications-subsystem.md) | Stages 7-8: LinkedIn leads + Hunter-verified cold email, new Leads DB, GitHub Actions | Step 6 (done) | XL |
| [step-10-auto-apply-subsystem.md](step-10-auto-apply-subsystem.md) | Proposed Stage 7: browser-automation capability router to submit applications, semi-auto by default. `scripts/autoapply.py` is the Phase 1 read-only-plan PoC (Greenhouse only, no submit) | Stage 2 (done), Notion status pipeline | L-XL (phaseable; Phase 1 PoC is S) |
| [step-11-forkable-setup.md](step-11-forkable-setup.md) | ✅ Notion half landed: `--init` wizard, `scripts/provision_notion.py` (page + both DBs), env-sourced `NOTION_DB_ID`, hardened `--setup`. ⏳ Deferred: profile.json, de-personalize tracked files | current setup surface | S (remaining) |
| [step-12-sponsorship-restriction-marker.md](step-12-sponsorship-restriction-marker.md) | Per-job Notion Notes marker to hold a specific posting from sponsorship tailoring, replacing the hardcoded `RESTRICTED_SPONSORSHIP_COMPANIES` list | Stage 2 sponsorship gate (done) | S |

Read `docs/TODO.md` first — it's the current index of exactly what's left, cross-referenced
to file:line. Each story here is the full spec for one TODO section.

## Source material

- [`../refinement-plans/README.md`](../refinement-plans/README.md) — the 1 remaining plan doc
  (4 are retired; see `../CHANGELOG.md`).
- [`../architecture/architecture-analysis.md`](../architecture/architecture-analysis.md) — the
  original three-horizon LLD/ERD/component analysis this backlog implements.
