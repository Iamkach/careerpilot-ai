# Refinement Plans — index

Originally five plan documents proposed changes to the AI job-search pipeline. Four are fully
implemented and retired; their content is summarized in [`../CHANGELOG.md`](../CHANGELOG.md):

- **Sourcing spike** (`sourcing/scraping-sources.md`) — resolved by the `valig`/`misceres`
  actor swap. Deleted.
- **Multi-source sourcing** (`sourcing/multi-source-sourcing.md`) — implemented as
  `scripts/sources.py`. Deleted.
- **Stage-1 filtering rework** (`filtering/stage1-filtering-rework.md`) — AI `company_type`
  classification, `Sponsorship`/`Retry` status handling, all landed as Step 5. Deleted.
- **Hybrid agentic migration** (`reliability/hybrid-agentic-migration-plan.md`) — reliability
  half (retries, typed errors, `Retry` status, kill fabricated `score=50`) landed as Step 5;
  the `AI_ROUTING`/tiering half was superseded by the shipped `FAST_PROVIDER`/`QUALITY_PROVIDER`
  design. Deleted.

Two plans remain and still describe unimplemented work. Open scope is tracked in
[`../TODO.md`](../TODO.md).

| Plan | Status | Covers |
|---|---|---|
| [`communications/communications-subsystem.md`](communications/communications-subsystem.md) | not started | Stages 7-8: LinkedIn leads + Hunter-verified cold email (Step 7) |
| [`ai-provider/runtime-ai-mode-flag.md`](ai-provider/runtime-ai-mode-flag.md) | not started | `run.py --ai-mode` — pick metered/hybrid/subscription AI routing per invocation (Step 8) |
