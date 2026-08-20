# Plan

## Open questions / Phase 0 spike (do before any code)

1. **Pick an actor.** A web search (2026-08) surfaced no official Wellfound API — only competing
   third-party Apify actors (`xtracto/wellfound-jobs-scraper`, `gio21/wellfound-jobs-scraper`,
   `thirdwatch/wellfound-jobs-scraper`, `scraper-engine/wellfound-angellist-jobs-scraper`,
   `clearpath/wellfound-api-ppe`, `orgupdate/wellfound-jobs-scraper`,
   `scrapebase/wellfound-jobs-scraper`, `radeance/wellfound-job-listings-scraper`,
   `jobsapi/wellfound-jobs-search-scraper`, `crawlerbros/wellfound-scraper`,
   `mscraper/wellfound-jobs-scraper`, `bovi/wellfound-jobs-scraper`). Run a small live test call
   against 2-3 candidates for one `TARGET_ROLES` entry; compare: result count, price/result,
   response schema stability, and whether fields this repo needs (posted date, salary range,
   description completeness) are actually populated — several of these actors' marketing pages
   claim overlapping features, only a live check disambiguates.
2. **Confirm the response schema**, then map it into the shared contract (`url, title, company,
   location, description, source="wellfound", posted_date, applicant_count, salary_range`) —
   follow `_apify_run()`'s existing polling pattern (`sources.py:70`) rather than a new HTTP client.
   `applicant_count`/`salary_range`/`posted_date` may not all be populated by every actor; `None`/`""`
   is fine, matching how `scrape_indeed` already degrades when Indeed's own listing omits a field.
3. **Cost sanity-check.** At the chosen actor's price/result and `WELLFOUND_MAX` × number of
   `TARGET_ROLES`, estimate per-run cost and compare against current LinkedIn/Indeed spend — this
   is the same evaluation `LINKEDIN_ACTOR`'s comment already documents having done once
   (replacing a broken $29.99/mo actor with a cheaper pay-per-event one).
4. **`SOURCE_PRIORITY` placement.** Decide where `"wellfound"` ranks. Reasoning candidate: below the
   ATS boards (which have the fullest JD + direct-apply URL) but likely above or below
   LinkedIn/Indeed depending on whether Wellfound listings tend to include a real posted date and
   full JD text (an ATS board's own strength) or are closer to LinkedIn's often-truncated listing —
   the Phase 0 sample from question 1 should settle this empirically, not by guess.

## Files (when implemented)

- **Modify:** `scripts/sources.py` — new `WELLFOUND_ACTOR` constant + `WELLFOUND_MAX`,
  `scrape_wellfound(role: str) -> list[dict]` (mirrors `scrape_linkedin`/`scrape_indeed`'s shape,
  reusing `_apify_run()`), add to `KEYWORD_SOURCES` and `SOURCE_PRIORITY`.
- **Modify:** `config/settings.py` — `"wellfound"` becomes a valid (but not default-on)
  `ENABLED_SOURCES` entry; any Wellfound-specific tuning constant if the actor needs one (e.g. a
  remote-only or startup-stage filter param) lives here, not hardcoded in `sources.py`.
- **New:** `tests/test_sources_wellfound.py` — fixture-based mapping test, following the shape of
  whatever existing test file covers `scrape_linkedin`/`scrape_indeed` (check `tests/` for the
  precedent before inventing a new fixture format).
- **Modify:** `CLAUDE.md` — add `wellfound` to the `KEYWORD_SOURCES` list in "Multi-source sourcing"
  and to the `ENABLED_SOURCES` description under "Stage 1 Filters".

## Risks

- **Actor churn.** Apify actors for a given site come and go / get renamed more often than
  first-party APIs (the LinkedIn actor comment already documents one such replacement). Whichever
  actor is chosen should be treated as swappable, not load-bearing — keep `scrape_wellfound()`'s
  actor id as a single named constant, same pattern as `LINKEDIN_ACTOR`/`INDEED_ACTOR`.
- **Anti-bot measures.** Some actor listings mention Wellfound running Cloudflare/DataDome
  protections that actors work around with stealth browsers — this can mean slower/flakier runs
  than the LinkedIn/Indeed actors currently in use; Phase 0's live test should note actual latency
  and failure rate, not just price.
- **Schema drift risk**, same class as the historical Indeed-actor incident CLAUDE.md documents —
  don't assume a marketing page's field list matches the real payload; verify with a live call
  first (Phase 0 question 2).
