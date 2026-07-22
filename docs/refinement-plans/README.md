# Refinement Plans — index

Originally six plan documents proposed changes to the AI job-search pipeline. Five are fully
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
- **Runtime `--ai-mode` flag** (`ai-provider/runtime-ai-mode-flag.md`) — landed as Step 8, plus
  an added `--metered-provider` flag and a new `openrouter` provider beyond the original spec.
  Deleted.

Two plans remain and still describe unimplemented work. Open scope is tracked in
[`../TODO.md`](../TODO.md).

| Plan | Status | Covers |
|---|---|---|
| [`communications/communications-subsystem.md`](communications/communications-subsystem.md) | not started | Stages 7-8: LinkedIn leads + Hunter-verified cold email (Step 7) |
| [`onboarding/forkable-setup.md`](onboarding/forkable-setup.md) | Notion half landed | ✅ `--init` wizard + `scripts/provision_notion.py` (page + both DBs) + env-sourced `NOTION_DB_ID` + hardened `--setup`. ⏳ Still deferred: `config/profile.json` identity/targets, untracking personal resume files, genericizing owner references (Step 11) |
| [`sourcing/career-site-enrichment-fallback.md`](sourcing/career-site-enrichment-fallback.md) | deferred — not queued, see trigger criteria | `generic_url_fetch()` gaps: no structured fields, JS-rendered SPAs return near-empty, no retry ceiling |
| [`auto-apply/ashby-workday-custom-fill.md`](auto-apply/ashby-workday-custom-fill.md) | deferred — not queued, see trigger criteria | Stage 7 Layer 2 browser fill only covers Greenhouse/Lever; Ashby/Workday/custom careers sites get an answer sheet only |
