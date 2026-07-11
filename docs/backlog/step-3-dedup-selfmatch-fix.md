# Step 3 — Dedup self-match fix (unblocks C8)

**Priority:** P0 — fixes manual intake **today** and unblocks two later stories.
**Depends on:** Step 2
**Blocks:** Step 5 (retry queue), Step 6 (fingerprint dedup) — both inherit this trap via
`db_get_all_jobs()` if it isn't fixed first (Conflict **C8**)
**Size:** XS (~10 lines)
**Source plan(s):**
[`refinement-plans/reliability/hybrid-agentic-migration-plan.md`](../refinement-plans/reliability/hybrid-agentic-migration-plan.md)
§3.5

## Context

Manually-added "Interested" jobs are supposed to bypass filters, get enriched, scored, and
promoted to `Scraped`. Instead, every one with a URL gets silently retired to `Scraped` with **no
score and no cached JD** — the intake path is broken today, not just a future risk.

## Current behavior

`ingest_interested_from_notion()` (`stage1_scrape.py:397`) calls
`db_find_job_by_url(page["url"])` for each Interested page. But that page **lives in the same jobs
DB and already holds that Job URL**, so `_query_db(filter_={"property": "Job URL", "url":
{"equals": url}})` (`utils.py:449-458`) matches the page against **itself**. The code then takes
the "already in DB, retiring" branch and promotes the page straight to `Scraped` with a blank
score.

The same trap exists in the dedup snapshot: `run()` builds `existing_urls` from **every** row
regardless of status (`stage1_scrape.py:540-541`), and `_pre_filter` drops on it (`:513`). A future
`Retry` row (Step 5) or a fingerprint set (Step 6) built from this same snapshot would drop a
queued job as a duplicate of itself on the next run.

## What to do

1. Give `db_find_job_by_url()` an `exclude_page_id: str = ""` parameter — skip a hit whose `id`
   equals it.
2. `ingest_interested_from_notion()` passes the row's own `page_id` as `exclude_page_id` when
   checking for an existing match.
3. Narrow the `existing_urls` snapshot build in `run()` (`stage1_scrape.py:540-541`) to exclude
   rows whose status is `Interested` (and, once it exists, `Retry`) — rebuild it from "is this job
   tracked under a **different**, already-settled row?" rather than "does this URL appear anywhere
   in the DB?"
4. While here: fix `scrape_job_urls()`'s silent `{}` return so a failed enrichment and an
   empty-but-successful one don't look alike (same silent-failure pattern as the Notion writer
   fixed in Step 2 — apply the same "log and distinguish" discipline).

## Acceptance criteria

- [ ] `db_find_job_by_url()` accepts `exclude_page_id` and correctly skips self-matches.
- [ ] Manual test: add a row by hand with `Status = Interested` and a real Job URL, run
      `python run.py --ingest`. It must be **enriched and scored**, landing on `Scraped` with a
      real ATS score and cached JD — not silently retired with a blank score.
- [ ] `existing_urls` snapshot excludes `Interested` (and any future `Retry`) rows, verified by
      re-running ingest twice in a row without the second run treating the first's output as a
      duplicate-of-self.
- [ ] `scrape_job_urls()` failure and empty-result cases are distinguishable in the logs.

## Out of scope

- The `Retry` status itself doesn't exist yet — this story only makes the exclusion logic correct
  in anticipation of it (use status list `{"Interested"}` now, extend to include `"Retry"` in
  Step 5 when that status is introduced).
- Fingerprint dedup (company+title) — Step 6.

## Files touched

`scripts/stage1_scrape.py` (`ingest_interested_from_notion`, `run()`'s snapshot build,
`scrape_job_urls`), `scripts/utils.py` (`db_find_job_by_url`).

## References

- Architecture analysis §B.8 risk M3; §D.1 risk register R7 (🟠).
- `refinement-plans/README.md` Step 3 and Conflict C8.
- `refinement-plans/reliability/hybrid-agentic-migration-plan.md` §3.5 (full technical detail).
