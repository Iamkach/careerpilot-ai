# Board-token harvesting

**Status:** finalized (re-scoped 2026-07-31 — see problem.md)
**Priority:** P2 — nothing is broken, but ATS-board coverage is stuck at ~23% and cannot improve
on its own. Every run pays LinkedIn/Indeed actor cost for jobs whose employer board could be
crawled for free.
**Size:** S for Phase 1 (the whole value), M for Phases 2-3.
**Depends-on:** [] — depends on Step 6 (`scripts/sources.py` registries, `discover_tokens()`,
`config/ats_tokens.json`), which is shipped but not yet migrated into `spec/` (historical
backfill pass).

Observe employer ATS-board tokens from URLs the pipeline already fetches, instead of only
guessing them from a slugified company name — converting `config/ats_tokens.json` entries from
`provenance: "guessed"` to `provenance: "observed"` wherever possible, and never re-probing an
observed entry.
