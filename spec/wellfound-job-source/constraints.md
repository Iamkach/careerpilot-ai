# Constraints

## Must fit the existing output contract

Every `KEYWORD_SOURCES` function returns `list[dict]` with exactly:
`url, title, company, location, description, source, posted_date, applicant_count, salary_range`
(`source.py` module docstring, lines 5-13). `scrape_wellfound(role: str) -> list[dict]` must match
this shape exactly — no new fields, no renamed ones — since `collapse_by_fingerprint()`,
`_pre_filter()`, and `score_jobs_batch()` all assume it unchanged.

## Cost is per-result, unbounded by default

Apify actors here are pay-per-event, the same as `valig~linkedin-jobs-scraper`
(`~$0.0004/result`, per the comment at `sources.py:55-58`). A `WELLFOUND_MAX` cap (mirroring
`LINKEDIN_MAX = 25` / `INDEED_MAX = 25` at `sources.py:63-64`) is required, not optional — an
unbounded per-role query across every `TARGET_ROLES` entry has no built-in ceiling otherwise.

## `discover_tokens()` / board-token infra does not apply here

This is a `KEYWORD_SOURCES` addition, not `BOARD_SOURCES` — no `config/ats_tokens.json` entry, no
`NOTION_TARGET_COMPANIES_PAGE_ID` interaction, no `title_matches_targets()` company-board filtering.
It follows `scrape_linkedin`/`scrape_indeed`'s simpler per-role-search shape.

## Actor payload → contract mapping must be verified against a real response

Every existing Apify actor integration (LinkedIn, Indeed) had its actual response schema checked
against a live call before shipping (`CLAUDE.md`'s note that a prior Indeed actor's "payload never
matched its schema" was a real incident). The Phase 0 spike (plan.md) must do the same for whichever
Wellfound actor is chosen before writing `scrape_wellfound()` against assumed field names.

## `ENABLED_SOURCES` opt-in, not on by default

New sources are additive to `config/settings.py`'s `ENABLED_SOURCES` list — landing the code
doesn't have to mean it's enabled for every existing user by default; that's a user/config decision
at rollout time, consistent with how `ENABLE_ATS_TOKEN_SEARCH_FALLBACK` and other feature flags in
this repo default rather than force-on.
