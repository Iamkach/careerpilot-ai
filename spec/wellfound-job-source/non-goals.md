# Non-goals

- **A keyless/board-style Wellfound integration.** No official public JSON API was found in initial
  research (see problem.md) — if that turns out to be wrong (a Phase 0 spike should re-check, since
  Wellfound could add one or an existing actor could expose a stable underlying endpoint), it would
  be a separate, later addition to `BOARD_SOURCES`, not part of this feature.
- **Picking a specific Apify actor without a cost/quality comparison.** Multiple competing actors
  exist (`xtracto`, `gio21`, `thirdwatch`, `scraper-engine`, `clearpath`, `orgupdate`, `scrapebase`,
  `radeance`, `jobsapi`, `crawlerbros`, `mscraper`, `bovi`, ...) at different price points and
  reliability; the Phase 0 spike (plan.md) picks one, this doc doesn't prejudge it.
- **Company-level Wellfound board crawling** (a `BOARD_SOURCES`-style per-company approach). Wellfound
  job search is role/keyword-driven in the UI the same way LinkedIn/Indeed are — no evidence a
  per-company board page exists the way Greenhouse/Lever/Ashby expose one.
- **Replacing LinkedIn/Indeed.** This is additive — one more `KEYWORD_SOURCES` entry, not a
  migration off the existing two.
