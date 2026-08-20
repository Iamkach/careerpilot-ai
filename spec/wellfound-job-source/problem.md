# Problem

Stage 1's sourcing (`scripts/sources.py`) currently covers two shapes:

- `KEYWORD_SOURCES` (`linkedin`, `indeed`) — paid Apify actors, searched per `TARGET_ROLES`.
- `BOARD_SOURCES` (`greenhouse`, `lever`, `ashby`) — free, keyless per-company JSON APIs, crawled
  per company via `discover_tokens()`.

Wellfound doesn't fit the `BOARD_SOURCES` shape — a web search turned up no official public/keyless
JSON API; every current access path is a third-party Apify actor scraping the rendered site (e.g.
`xtracto/wellfound-jobs-scraper`, `gio21/wellfound-jobs-scraper`, `thirdwatch/wellfound-jobs-scraper`
— several competing actors, priced pay-per-result the same way `valig~linkedin-jobs-scraper` is).
So this is a `KEYWORD_SOURCES` addition, not a `BOARD_SOURCES` one — same shape as `linkedin`/
`indeed`, not `greenhouse`/`lever`/`ashby`.

Today the user only gets Wellfound listings if a company happens to also run a Greenhouse/Lever/
Ashby board (`BOARD_SOURCES` already covers that) or shows up on LinkedIn/Indeed — a
Wellfound-exclusive posting (common for early-stage startups that don't yet run a full ATS) is
invisible to the pipeline.

## Goal

Add `wellfound` to `KEYWORD_SOURCES`, following the exact shape `scrape_linkedin()`/
`scrape_indeed()` already establish: one Apify actor call per `TARGET_ROLES` entry, mapped into the
shared output contract (`url, title, company, location, description, source, posted_date,
applicant_count, salary_range`), then folded into the same global gather → collapse → filter →
score pipeline `stage1_scrape.py` already runs — no changes needed downstream of `sources.py`.
