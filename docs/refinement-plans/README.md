# Refinement Plans — index

Originally five plan documents proposed changes to the AI job-search pipeline. Two are fully
implemented and retired; their content is summarized in [`../CHANGELOG.md`](../CHANGELOG.md):

- **Sourcing spike** (`sourcing/scraping-sources.md`) — resolved by the `valig`/`misceres`
  actor swap. Deleted.
- **Multi-source sourcing** (`sourcing/multi-source-sourcing.md`) — implemented as
  `scripts/sources.py`. Deleted.

The three remaining plans still describe unimplemented work and stay as specs. Open scope for
each is tracked in [`../TODO.md`](../TODO.md).

| Plan | Status | Covers |
|---|---|---|
| [`filtering/stage1-filtering-rework.md`](filtering/stage1-filtering-rework.md) | §1-2 done, §3-9 open | AI `company_type` classification, sponsorship gating (Step 5) |
| [`reliability/hybrid-agentic-migration-plan.md`](reliability/hybrid-agentic-migration-plan.md) | tiering half superseded, reliability half open | retries, typed errors, `Retry` status, kill fabricated score=50 (Step 5) |
| [`communications/communications-subsystem.md`](communications/communications-subsystem.md) | not started | Stages 7-8: LinkedIn leads + Hunter-verified cold email (Step 7) |

The filtering and reliability plans are merged into one execution story — Step 5 — because
they both rewrite `score_jobs_batch()` and would conflict if implemented separately (see each
plan's own status banner for the resolution). Read `../backlog/step-5-reliability-and-filtering-merge.md`
before starting that work.
