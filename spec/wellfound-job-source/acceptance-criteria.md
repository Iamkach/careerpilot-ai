# Acceptance criteria

- [ ] Phase 0 spike (actor selection, live schema check, cost sanity-check — see plan.md)
      completed before any code is written.
- [ ] `scrape_wellfound(role: str) -> list[dict]` exists in `scripts/sources.py`, returns the exact
      shared output contract, and is added to `KEYWORD_SOURCES`.
- [ ] `"wellfound"` added to `SOURCE_PRIORITY` with a documented rationale for its rank relative to
      the ATS boards and LinkedIn/Indeed.
- [ ] `WELLFOUND_MAX` (or equivalent) caps results per role, mirroring `LINKEDIN_MAX`/`INDEED_MAX`.
- [ ] `"wellfound"` is a valid `ENABLED_SOURCES` entry but is **not** added to the default list —
      opt-in only, per constraints.md.
- [ ] A Wellfound-sourced job that's also on a Greenhouse/Lever/Ashby board for the same company
      collapses to one row via `collapse_by_fingerprint()`, keeping the board copy.
- [ ] A test using a recorded/fixture Apify response proves the mapping into the shared contract,
      following the existing `patch_ai_chat`/`patch_notion_db` fake pattern in `tests/conftest.py`
      (no live Apify call in the default suite).
