# Plan

## Already implemented (D, A, B)

- **D:** `Enrichment Attempts` (Notion number property, optionally-present) + `MAX_ENRICHMENT_ATTEMPTS`
  (`config/settings.py`) — `ingest_interested_from_notion()` gives up after the ceiling and
  promotes to `Scraped` with a `Notes` marker.
- **A:** `_extract_jobposting_jsonld()` (`scripts/sources.py`) — `generic_url_fetch()` tries a
  schema.org `JobPosting` JSON-LD block before falling back to raw `<title>`/tag-stripped text.
- **B:** `_headless_fetch()` (Playwright, optional dependency — see `requirements-optional.txt`) —
  when both the JSON-LD probe and the raw-text fallback come up short, renders the page with
  headless Chromium and retries the identical extraction (`_parse_fetched_html()`) against the
  hydrated HTML. Never raises; degrades to `None` (the existing enrichment-failure path) if
  Playwright isn't installed or the render fails.

## If Option C is ever picked up

**Files:** `scripts/sources.py` (`generic_url_fetch()` gains a `_paid_scrape_fetch()` helper,
called only when the static path and the JSON-LD probe both come up short — replacing or
supplementing `_headless_fetch()`'s role, per whichever trigger fired); no change expected to
`scripts/stage1_scrape.py` or the Notion schema, since D/A are already in place and C only swaps
the mechanism behind gap #2's fallback.
