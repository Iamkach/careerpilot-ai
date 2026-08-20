# Constraints

## Options considered

| Option | What it buys | Cost |
|---|---|---|
| **A. Better static parsing** — try common JSON-LD (`<script type="application/ld+json">` `JobPosting` schema, which Greenhouse/Lever/Workday/many ATSes emit even in SPA shells) before falling back to raw `<title>`/tag-stripping; add an og:site_name / domain-based company guess. | Fixes gap #1 for a meaningful subset of sites for free — many SPAs still emit JSON-LD in server-rendered `<head>` even though the visible DOM is client-rendered. | Small — pure-Python, no new dependency, isolated to `generic_url_fetch()`. **Shipped.** |
| **B. Headless rendering** (Playwright/Selenium) for sites where option A's JSON-LD probe and the raw-HTML fetch both come up short. | Fixes gap #2 properly — executes JS, sees the real hydrated DOM. | Real infra weight: new dependency, browser binary in CI/runtime, slower and heavier per call. **Shipped**, as an optional dependency that degrades gracefully when absent. |
| **C. Paid scraping API** (e.g. ScraperAPI, Browserless, or reusing the existing Apify account with a generic-URL actor) as the SPA fallback instead of self-hosting a headless browser. | Fixes gap #2 without owning browser infra; consistent with how the pipeline already pays Apify for LinkedIn/Indeed. | Ongoing marginal cost per call; another vendor dependency. **Still deferred — see meta.md's Trigger.** |
| **D. Retry ceiling for enrichment** — mirror `MAX_SCORING_ATTEMPTS`: track an `Enrichment Attempts` count, give up after N failed `--ingest` passes by promoting to `Scraped` with an explicit `Notes` marker ("enrichment failed — add JD manually") instead of retrying forever. | Fixes gap #3, independent of A/B/C. | Small — one counter + one gate, same shape as the existing scoring-retry queue. **Shipped.** |

## Recommended sequencing (already followed)

1. **D first** (retry ceiling) — cheapest, prevents the silent-forever-retry problem regardless of
   which enrichment approach is active, and had a direct precedent to copy
   (`rescore_retry_jobs()` in `scripts/stage1_scrape.py`).
2. **A next** (JSON-LD + basic company/location parsing) — no new dependency, fixes the common case.
3. **B or C only if A still leaves real failures** — pick headless (B) if this fires often enough
   to amortize the infra cost and the team wants no new billing dependency; pick a paid API (C) if
   it's occasional and matches the existing "pay Apify for the parts that need real scraping"
   pattern. **B was chosen and shipped; C remains available if B's cost profile changes.**
