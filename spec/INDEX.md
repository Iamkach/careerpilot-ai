# Spec index

Every feature lives in its own `spec/<feature-name>/` folder: `meta.md` (status, priority, size,
depends-on), `problem.md`, `end-goal.md`, `non-goals.md`, `constraints.md`,
`acceptance-criteria.md`, `plan.md`, `verification.md`. Copy `spec/_template/` to start a new one.

Status vocabulary (see each feature's `meta.md`): `idea` → `finalized` → `in-progress` → `done`,
with `deferred` (parked pending a trigger), `blocked` (waiting on an external decision, see the
callout below), and `superseded` (dropped in favor of something else) as side states.

## Backlog triage (2026-09-27)

A full keep/defer/drop pass across every open epic and spec ran via the wayfinder skill — see
[triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61) for the full record. Outcome:

- **Dropped outright:** `application-prefill-extension` (Layer 3, MV3 extension — designed
  incorrectly, unreliable in real use) and its dependents `extension-ux-fixes`, plus the unmerged
  remainder and live-verification stories. Superseded by the Claude-in-Chrome fill flow
  (Layer 4a — confirmed 2026-08-05, tracked in issues #24-#36, folded into #61).
- **Reframed as fog (not droppable, not yet a real ticket):** `wellfound-job-source` and
  `communications-subsystem`/`inbound-email-status-sync` merged into one open question — a
  lightweight, agentic browser-workflow approach to both sourcing and inbound status sync,
  replacing both specs' original heavier designs. See #61's "Not yet specified."
- **Elevated to top priority:** `resume-tailoring-prose-quality` (#1 of 5) — verbatim keyword
  substitution is affecting actual application quality, not cosmetic.
- **Still open, unreconciled:** `auto-apply-agentic-submit` (Layer 4b) against the confirmed
  Layer 4a decision — tracked as [#45](https://github.com/Iamkach/careerpilot-ai/issues/45) on #61.
  See [`../docs/adr/0001-stage7-execution-strategy.md`](../docs/adr/0001-stage7-execution-strategy.md).

| Feature | Status | Priority | Size | Depends-on |
|---|---|---|---|---|
| [resume-tailoring-prose-quality](resume-tailoring-prose-quality/meta.md) | finalized — top priority (#1 of 5), see #61 | P1 | M | — |
| [auto-apply-subsystem](auto-apply-subsystem/meta.md) | in-progress (Phases 1-2 shipped; Phase 3-4 blocked, see ADR 0001) | P2 | L-XL | — |
| [board-token-harvesting](board-token-harvesting/meta.md) | finalized | P2 | S (Phase 1), M (Phases 2-3) | — |
| [career-site-enrichment-fallback](career-site-enrichment-fallback/meta.md) | deferred (mostly shipped; only Option C remains gated) | — | S | — |
| [selector-resolution-hardening](selector-resolution-hardening/meta.md) | superseded (Phase 1-2 implemented and reused; Phase 3 close-out tracked as #46) | P2 | S | — |
| [auto-apply-agentic-submit](auto-apply-agentic-submit/meta.md) | blocked — pending ADR 0001 and #45 | P1 | L | selector-resolution-hardening |
| [wellfound-job-source](wellfound-job-source/meta.md) | idea — reframed as fog on #61, original scraper design dropped | — | — (unscoped) | — |
| [communications-subsystem](communications-subsystem/meta.md) | superseded — original XL design dropped, merged into fog on #61 | — | — | — |
| [inbound-email-status-sync](inbound-email-status-sync/meta.md) | superseded — merged into fog on #61 | — | — | — |
| [application-prefill-extension](application-prefill-extension/meta.md) | superseded — decommissioned 2026-09-27, see #61 | — | — | — |
| [extension-ux-fixes](extension-ux-fixes/meta.md) | superseded — dropped with application-prefill-extension | — | — | application-prefill-extension |

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
