# Spec index

Every feature lives in its own `spec/<feature-name>/` folder: `meta.md` (status, priority, size,
depends-on), `problem.md`, `end-goal.md`, `non-goals.md`, `constraints.md`,
`acceptance-criteria.md`, `plan.md`, `verification.md`. Copy `spec/_template/` to start a new one.

Status vocabulary (see each feature's `meta.md`): `idea` → `finalized` → `in-progress` → `done`,
with `deferred` (parked pending a trigger) and `superseded` (dropped in favor of something else)
as side states.

| Feature | Status | Priority | Size | Depends-on |
|---|---|---|---|---|
| [communications-subsystem](communications-subsystem/meta.md) | idea (blocked on Phase-0 spike) | P3 | XL | — |
| [auto-apply-subsystem](auto-apply-subsystem/meta.md) | in-progress (Phases 1-2 shipped; Phase 3-4 open) | P2 | L-XL | — |
| [board-token-harvesting](board-token-harvesting/meta.md) | finalized | P2 | S (Phase 1), M (Phases 2-3) | — |
| [application-prefill-extension](application-prefill-extension/meta.md) | in-progress (implemented, live verification + commit outstanding) | — | L | — |
| [extension-ux-fixes](extension-ux-fixes/meta.md) | finalized | P1 | S | application-prefill-extension |
| [career-site-enrichment-fallback](career-site-enrichment-fallback/meta.md) | deferred (mostly shipped; only Option C remains gated) | — | S | — |
| [inbound-email-status-sync](inbound-email-status-sync/meta.md) | idea | — | — | — |

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
