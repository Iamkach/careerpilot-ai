# Backlog — remaining work

## Scope: backlog vs. refinement-plans

This directory holds a story **once its design is finalized and lined up to be implemented**.
[`../refinement-plans/`](../refinement-plans/) holds a plan while it's still at idea/discussion
level (not finalized, or finalized but deliberately deferred pending a trigger).

When a plan there gets finalized and queued, fold its content into a `step-N-*.md` story here —
condense the "why" (sources considered/rejected, binding decisions, risks) alongside the
implementation checklist — and **delete** the refinement-plan doc; don't leave it as a duplicate
"full spec" this story points back to. One doc per story once it's queued. See
[`../refinement-plans/README.md`](../refinement-plans/README.md) for the reverse direction.

---

Steps 0-1, 2-6, 8, 9, 10, 11, 12, 14 (plus both quick-fixes' first item) are implemented **and on
GitHub's `main`** — see [`../CHANGELOG.md`](../CHANGELOG.md) for what shipped and
[`../TODO.md`](../TODO.md) for the small, standalone gaps each left behind (a missing
`encoding="utf-8"`, an unlogged bare `except`, two unrun manual QA checks — the handful of gaps
Step 9's test suite had characterized as not-yet-fixed are now fixed, see `../TODO.md`). Step 10
and Step 11 landed together via PR #19 (Step 11 into `feature/step-10-auto-apply`) then PR #20
(that branch into `main`, 2026-07-30). Step 14 lands via this branch.

Open stories:

| Story | What it does | Depends on | Size |
|---|---|---|---|
| [step-7-communications-subsystem.md](step-7-communications-subsystem.md) | Stages 7-8: LinkedIn leads + Hunter-verified cold email, new Leads DB, GitHub Actions | Step 6 (done) | XL |
| [step-13-board-token-harvesting.md](step-13-board-token-harvesting.md) | Harvest the employer ATS board URL that LinkedIn/Indeed listings already carry (and we discard), so `config/ats_tokens.json` is built by **observation** instead of slug-guessing — today 23/100 companies resolve to a board | Step 6 (done) | S (Phase 1 = the whole value) |
| [step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) | Stage 7 **Layer 3**: MV3 extension + localhost bridge that pre-fills the application form open in your own authenticated browser — live DOM is the schema, so Ashby/Workday/custom career sites are one code path. Attaches the tailored resume, surfaces essay drafts for review, and confirms `Applied` to Notion from the popup | Step 10 Phases 1-2 (done) | L |

Each story here is fully self-contained — problem statement, binding decisions, and its own
"open residual gaps" list, kept current in the story itself rather than duplicated in
`docs/TODO.md`. `docs/TODO.md` is scoped to small, standalone fixes/reminders only, not a roadmap
index — read the table above for what's open, and open the story directly for the current state.

## Source material

- [`../refinement-plans/README.md`](../refinement-plans/README.md) — 2 plans remain, still
  idea-level/deferred (7 are retired or folded in; see `../CHANGELOG.md`), plus
  `auto-apply/sourcing-bottleneck-analysis.md`, kept as a measurement record rather than a plan.
- [`../architecture/architecture-analysis.md`](../architecture/architecture-analysis.md) — the
  original three-horizon LLD/ERD/component analysis this backlog implements.
