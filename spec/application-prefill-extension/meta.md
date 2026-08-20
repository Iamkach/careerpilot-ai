# Application pre-fill browser extension (Stage 7 Layer 3)

**Status:** in-progress — all ten increments below are coded, wired in, and covered by `pytest`
(Python side) / grep contract tests (JS side). **Not yet closed out:** live verification in a real
Chrome session (every increment's own checklist) and installing/testing the native-messaging host
(increment 8) haven't been run yet, and nothing here is committed — see verification.md's
"Remaining before this story can close."
**Size:** L
**Depends-on:** [] — depends on Step 10 Phases 1-2 (shipped, not yet migrated into `spec/`).

Cuts the ~20 min/application spent in the browser for new inbound jobs, via a docked Chrome side
panel + local HTTP bridge that pre-fills whatever application form is on screen — Ashby, Workday,
and arbitrary custom career sites become one code path instead of needing a per-ATS Playwright
adapter.

## Doc history

Originally split (2026-07-30) into ten sub-stories (`step-15a`-`step-15j`) so each could ship and
be verified independently, then unified back into one doc (2026-08-01) once every increment
shipped — one doc per story, per the repo's fold-and-delete convention, rather than ten files whose
only remaining reason to exist was in-flight independent tracking. Originally folded from
`docs/refinement-plans/auto-apply/browser-extension-prefill.md`. Migrated from
`docs/backlog/step-15-application-prefill-extension.md` into this `spec/` structure as part of the
docs restructure (see `spec/inbound-email-status-sync/` sibling migration for the same pass).
`docs/refinement-plans/auto-apply/sourcing-bottleneck-analysis.md` (referenced below, "do not
re-derive") is relocated to `docs/research/sourcing-bottleneck-analysis.md` in the same pass.
