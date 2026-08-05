# Problem

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

This plan was **not scheduled** when originally written — `docs/TODO.md` deferred it explicitly:
"revisit only if a real `Interested` URL is observed failing this way." Gaps #1-#3 (options D, A,
B below) were subsequently implemented ahead of that trigger, at explicit user request. Only
Option C remains behind a trigger — see meta.md.
