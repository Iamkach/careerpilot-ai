# Career-site enrichment fallback — closing the generic_url_fetch gap

*See [`../README.md`](../README.md) for how this plan relates to the others. Baseline: `feature/god-speed`, after commit b8504a3.*

**Status (2026-07-19): D, A, and B implemented (built ahead of the trigger criteria, at explicit
user request — no real SPA-with-no-JSON-LD failure has actually been observed yet).**
`Enrichment Attempts` (Notion number property, optionally-present) + `MAX_ENRICHMENT_ATTEMPTS`
(`config/settings.py`) close gap #3 — `ingest_interested_from_notion()` now gives up after
`MAX_ENRICHMENT_ATTEMPTS` failed passes and promotes the row to `Scraped` with a `Notes` marker
instead of retrying forever. `_extract_jobposting_jsonld()` (`scripts/sources.py`) closes gap #1
(and part of #2) — `generic_url_fetch()` tries a schema.org `JobPosting` JSON-LD block before
falling back to raw `<title>`/tag-stripped text. `_headless_fetch()` (Playwright, optional
dependency — see `requirements.txt`) closes the rest of gap #2 — when both the JSON-LD probe and
the raw-text fallback come up short on the static GET, `generic_url_fetch()` renders the page
with headless Chromium and retries the identical extraction (`_parse_fetched_html()`) against the
hydrated HTML. Degrades gracefully (logs a warning, returns `None`, exactly like any other
enrichment miss) if Playwright isn't installed or the render itself fails — never a hard error.
C (a paid scraping API, as a no-new-infra alternative to B) remains deferred; only worth adding if
Playwright/Chromium proves too heavy to run in the pipeline's actual environment (e.g. the
nightly GitHub Actions runner) or B is observed failing often in practice.

## Context

`ingest_interested_from_notion()` (`scripts/stage1_scrape.py`) enriches a hand-picked `Interested`
job URL before scoring it. `enrich_job_url()` (`scripts/sources.py`) dispatches by domain:
Greenhouse/Lever/Ashby URLs hit their real per-job JSON APIs (title, company, location, full JD as
separate structured fields); everything else falls through to `generic_url_fetch()` — one
`requests.get()` plus regex HTML-tag stripping. That fallback is what fixed the original bug (jobs
were being scored on a blank description and landing in Notion with a fabricated-looking score),
but it's a floor, not a real scraper, with three known gaps:

1. **No structured fields.** `company`/`location` always come back `""`; `title` is whatever the
   page's `<title>` tag says, boilerplate suffix and all (e.g.
   `"Software Development Engineer, AWS OpenSearch Service - Job ID: 10475195 | Amazon.jobs"`).
2. **JS-rendered SPAs return near-nothing.** No JavaScript executes, so a client-hydrated career
   page (Workday, custom React/Vue) can come back as an empty shell. Guarded only by "stripped text
   under 200 chars → treat as failure," which is a blunt proxy in both directions — a legitimately
   short JD could fail it, while a JS shell's static boilerplate (nav/footer/cookie banner) could
   clear 200 chars while still carrying no real JD.
3. **No retry ceiling.** A permanently unfetchable URL is retried identically on every `--ingest`
   run forever — unlike `rescore_retry_jobs()`'s `MAX_SCORING_ATTEMPTS` on the scoring side.

This plan is **not scheduled**. `docs/TODO.md` explicitly defers it — "revisit only if a real
`Interested` URL is observed failing this way." It exists so that when that happens, there's a
ready decision instead of a scramble.

## Trigger criteria — when to actually pick this up

Watch for one of these before spending implementation time:
- A real `Interested`/scratch-note URL logs `⚠ Generic fetch ... returned too little text` (or
  keeps re-appearing in the `Interested` list run after run because it never enriches).
- The blank-`Company`/junk-`title` cosmetic issue becomes annoying enough in daily Notion review to
  be worth fixing on its own (Option A below — cheap, no new dependency).

## Options considered

| Option | What it buys | Cost |
|---|---|---|
| **A. Better static parsing** — try common JSON-LD (`<script type="application/ld+json">` `JobPosting` schema, which Greenhouse/Lever/Workday/many ATSes emit even in SPA shells) before falling back to raw `<title>`/tag-stripping; add an og:site_name / domain-based company guess. | Fixes gap #1 for a meaningful subset of sites for free — many SPAs still emit JSON-LD in server-rendered `<head>` even though the visible DOM is client-rendered. | Small — pure-Python, no new dependency, isolated to `generic_url_fetch()`. |
| **B. Headless rendering** (Playwright/Selenium) for sites where option A's JSON-LD probe and the raw-HTML fetch both come up short. | Fixes gap #2 properly — executes JS, sees the real hydrated DOM. | Real infra weight: new dependency, browser binary in CI/runtime, slower (seconds not ms) and heavier per call. Only worth it if this path fires often. |
| **C. Paid scraping API** (e.g. ScraperAPI, Browserless, or reusing the existing Apify account with a generic-URL actor) as the SPA fallback instead of self-hosting a headless browser. | Fixes gap #2 without owning browser infra; consistent with how the pipeline already pays Apify for LinkedIn/Indeed. | Ongoing marginal cost per call; another vendor dependency. |
| **D. Retry ceiling for enrichment** — mirror `MAX_SCORING_ATTEMPTS`: track an `Enrichment Attempts` count (new Notion property or reuse `Scoring Attempts`), give up after N failed `--ingest` passes by promoting to `Scraped` with an explicit `Notes` marker ("enrichment failed — add JD manually") instead of retrying forever. | Fixes gap #3, independent of A/B/C. | Small — one counter + one gate, same shape as the existing scoring-retry queue. |

## Recommended sequencing (when triggered)

1. **D first** (retry ceiling) — cheapest, prevents the silent-forever-retry problem regardless of
   which enrichment approach is active, and has a direct precedent to copy
   (`rescore_retry_jobs()` in `scripts/stage1_scrape.py`).
2. **A next** (JSON-LD + basic company/location parsing) — no new dependency, fixes the common case
   (most modern ATS-hosted or SEO-conscious career pages emit `JobPosting` JSON-LD even when the
   visible page is a SPA shell).
3. **B or C only if A still leaves real failures** — pick headless (B) if this fires often enough
   to amortize the infra cost and the team wants no new billing dependency; pick a paid API (C) if
   it's occasional and matches the existing "pay Apify for the parts that need real scraping"
   pattern.

## Files (when implemented)

- **Modify:** `scripts/sources.py` (`generic_url_fetch()` gains a JSON-LD probe for A; a new
  `_headless_fetch()` or `_paid_scrape_fetch()` helper for B/C, called only when the static path
  comes up short)
- **Modify:** `scripts/stage1_scrape.py` (`ingest_interested_from_notion()` for D's attempt-count
  gate, mirroring `rescore_retry_jobs()`'s pattern)
- **Modify (D only):** Notion schema — either reuse `Scoring Attempts` or add a new
  `Enrichment Attempts` number property (update `CLAUDE.md`'s schema section if added)

## Verification (when implemented)

1. **A:** point at 2-3 real SPA career pages with known JSON-LD (test manually with `curl` first to
   confirm the `<script type="application/ld+json">` block exists); confirm `generic_url_fetch()`
   now returns a real `company`/`location`, not blank.
2. **B/C:** point at a confirmed SPA failure case from the trigger criteria; confirm real JD text
   comes back where the static fetch previously failed the 200-char guard.
3. **D:** force 3+ consecutive enrichment failures on a test URL; confirm it stops retrying after
   the ceiling and lands in a clearly-marked terminal state instead of looping forever.
