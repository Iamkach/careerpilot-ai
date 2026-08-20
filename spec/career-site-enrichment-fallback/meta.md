# Career-site enrichment fallback

**Status:** deferred — D, A, and B are already implemented (built ahead of the original trigger
criteria, at explicit user request — no real SPA-with-no-JSON-LD failure has actually been
observed yet). Only **Option C** (a paid scraping API, as a no-new-infra alternative to B) remains
genuinely deferred.
**Trigger (for C only):** only worth adding if Playwright/Chromium proves too heavy to run in the
pipeline's actual environment (e.g. the nightly GitHub Actions runner) or Option B is observed
failing often in practice.
**Depends-on:** []

Closes gaps in `generic_url_fetch()` (`scripts/sources.py`), the fallback enrichment path for
hand-picked "Interested" job URLs that don't hit Greenhouse/Lever/Ashby's real per-job JSON APIs.
Baseline: `feature/god-speed`, after commit `b8504a3`.

## What already shipped

`Enrichment Attempts` (Notion number property, optionally-present) + `MAX_ENRICHMENT_ATTEMPTS`
(`config/settings.py`) close gap #3 (no retry ceiling) — `ingest_interested_from_notion()` now
gives up after `MAX_ENRICHMENT_ATTEMPTS` failed passes and promotes the row to `Scraped` with a
`Notes` marker instead of retrying forever. `_extract_jobposting_jsonld()` (`scripts/sources.py`)
closes gap #1 (and part of #2) — `generic_url_fetch()` tries a schema.org `JobPosting` JSON-LD
block before falling back to raw `<title>`/tag-stripped text. `_headless_fetch()` (Playwright,
optional dependency) closes the rest of gap #2 — when both the JSON-LD probe and the raw-text
fallback come up short on the static GET, `generic_url_fetch()` renders the page with headless
Chromium and retries the identical extraction against the hydrated HTML. Degrades gracefully (logs
a warning, returns `None`, exactly like any other enrichment miss) if Playwright isn't installed or
the render itself fails — never a hard error.
