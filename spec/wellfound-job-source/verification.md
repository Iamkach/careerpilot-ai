# Verification (when implemented)

1. Unit test mocking the Apify actor response (list + get, following `_apify_run()`'s existing HTTP
   shape) against a real captured sample from the Phase 0 spike, asserting `scrape_wellfound()`
   maps every field into the shared output contract correctly, including graceful `None`/`""`
   handling for fields the actor doesn't populate.
2. A test proving a Wellfound-sourced listing and a Greenhouse-sourced listing for the same
   company+title collapse to one row via `collapse_by_fingerprint()`, keeping the higher-priority
   copy per the `SOURCE_PRIORITY` placement decided in plan.md.
3. `pytest -v` stays green and fast (~1.5s) — no live Apify call in the default suite, matching
   CLAUDE.md's "Testing a Change" bar.
4. Manual: run `python run.py --stage 1` with `ENABLED_SOURCES` including `"wellfound"` against 1-2
   real `TARGET_ROLES`, confirm listings land in Notion with `Source = "wellfound"` and plausible
   `Posted Date`/`Salary Range` where the actor provides them, and sanity-check actual per-run cost
   against the Phase 0 estimate.
