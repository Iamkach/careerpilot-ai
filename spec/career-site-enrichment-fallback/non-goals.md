# Non-goals

- **Building Option C before its trigger fires.** Only worth adding if Playwright/Chromium proves
  too heavy for the pipeline's actual runtime (e.g. the nightly GitHub Actions runner), or Option B
  is observed failing often in practice. Neither has happened yet.
- **A general-purpose scraper.** This stays a floor/fallback for the one case
  (Greenhouse/Lever/Ashby's real per-job JSON APIs already cover the common case) — not an attempt
  to out-scrape a dedicated career-site parser.
