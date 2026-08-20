# Spec index

Every feature lives in its own `spec/<feature-name>/` folder: `meta.md` (status, priority, size,
depends-on), `problem.md`, `end-goal.md`, `non-goals.md`, `constraints.md`,
`acceptance-criteria.md`, `plan.md`, `verification.md`. Copy `spec/_template/` to start a new one.

Status vocabulary (see each feature's `meta.md`): `idea` → `finalized` → `in-progress` → `done`,
with `deferred` (parked pending a trigger), `blocked` (waiting on an external decision, see the
callout below), and `superseded` (dropped in favor of something else) as side states.

## ⚠ Decisions needed

**Stage 7 (auto-apply) has four competing, unreconciled execution strategies in flight at once —
`auto-apply-subsystem` (Layer 2), `application-prefill-extension` (Layer 3, MV3 extension),
a Claude-in-Chrome fill flow (Layer 4a — tracked only in GitHub issues #24-#32, no `spec/` folder,
already confirmed 2026-08-05 as replacing Layer 3), and `auto-apply-agentic-submit` (Layer 4b,
written 2026-08-10 without referencing Layer 4a's decisions) — with 4 open GitHub issues (#24,
#33, #34, #36) already asking which one wins.** See
[`../docs/adr/0001-stage7-execution-strategy.md`](../docs/adr/0001-stage7-execution-strategy.md)
for the consolidated comparison. Not decided yet — read that before picking up any one of the
specs below in isolation.

| Feature | Status | Priority | Size | Depends-on |
|---|---|---|---|---|
| [communications-subsystem](communications-subsystem/meta.md) | idea (blocked on Phase-0 spike) | P3 | XL | — |
| [auto-apply-subsystem](auto-apply-subsystem/meta.md) | in-progress (Phases 1-2 shipped; Phase 3-4 blocked, see ADR 0001) | P2 | L-XL | — |
| [board-token-harvesting](board-token-harvesting/meta.md) | finalized | P2 | S (Phase 1), M (Phases 2-3) | — |
| [application-prefill-extension](application-prefill-extension/meta.md) | in-progress (core landed on main; drafts.js + native-messaging host still unmerged, see meta.md; live verification outstanding; blocked on ADR 0001 for further build-out) | — | L | — |
| [extension-ux-fixes](extension-ux-fixes/meta.md) | finalized | P1 | S | application-prefill-extension |
| [career-site-enrichment-fallback](career-site-enrichment-fallback/meta.md) | deferred (mostly shipped; only Option C remains gated) | — | S | — |
| [inbound-email-status-sync](inbound-email-status-sync/meta.md) | idea | — | — | — |
| [wellfound-job-source](wellfound-job-source/meta.md) | idea | — | S–M | — |
| [resume-tailoring-prose-quality](resume-tailoring-prose-quality/meta.md) | idea | — | M | — |
| [selector-resolution-hardening](selector-resolution-hardening/meta.md) | superseded (Phase 1-2 implemented and reused; Phase 3 superseded) | P2 | S | — |
| [auto-apply-agentic-submit](auto-apply-agentic-submit/meta.md) | blocked — pending ADR 0001 | P1 | L | selector-resolution-hardening |

This table covers currently-open work only. ~14 already-shipped steps (0-1, 2-6, 8, 9, 11, 12, and
`auto-apply-subsystem`'s Phases 1-2) are documented in [`../docs/CHANGELOG.md`](../docs/CHANGELOG.md)
and have not yet been retrofitted into this `spec/` shape — a deliberately separate, later pass
(the only surviving source material for those is `CHANGELOG.md` prose, since their original
refinement-plan docs were already deleted per this repo's fold-and-delete history).

## Source material

- [`../docs/architecture/architecture-analysis.md`](../docs/architecture/architecture-analysis.md) —
  the original three-horizon LLD/ERD/component analysis this backlog implements.
- [`../docs/research/`](../docs/research/) — measurement records and analysis snapshots that
  inform a feature's `problem.md` but aren't specs themselves (e.g.
  `sourcing-bottleneck-analysis.md`, referenced from `application-prefill-extension/problem.md`).
- [`../docs/CHANGELOG.md`](../docs/CHANGELOG.md) — what's shipped, in narrative form, until the
  historical backfill pass above happens.
- [`../docs/TODO.md`](../docs/TODO.md) — small, standalone gaps and reminders; not a roadmap index.
