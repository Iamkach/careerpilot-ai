# Application pre-fill browser extension (Stage 7 Layer 3)

**Status:** superseded — decommissioned outright 2026-09-27, see
[triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61) and closed
[#34](https://github.com/Iamkach/careerpilot-ai/issues/34): the extension's fill mechanism is
unreliable in real Chrome use despite passing automated tests, and is not worth debugging back to
reliable. The unmerged remainder (`extension/drafts.js`, native-messaging host) will **not** be
landed — closed as [#42](https://github.com/Iamkach/careerpilot-ai/issues/42). Live-Chrome
verification will **not** be run — closed as [#43](https://github.com/Iamkach/careerpilot-ai/issues/43).
Superseded outright by the Claude-in-Chrome fill flow (#24's confirmed destination, folded into #61).
**Size:** L
**Depends-on:** [] — depends on Step 10 Phases 1-2 (shipped, not yet migrated into `spec/`).

One of four unreconciled directions for Stage 7's execution strategy — see
[docs/adr/0001-stage7-execution-strategy.md](../../docs/adr/0001-stage7-execution-strategy.md).
**Note:** GitHub issue [#27](https://github.com/Iamkach/careerpilot-ai/issues/27) already
confirmed (2026-08-05) that a Claude-in-Chrome fill flow supersedes this extension outright —
that decision was never reflected here or in this file's Status field; see the ADR before
treating this as still the active plan. Only [#34](https://github.com/Iamkach/careerpilot-ai/issues/34)
(decommission timing) remains genuinely open on that question.

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
