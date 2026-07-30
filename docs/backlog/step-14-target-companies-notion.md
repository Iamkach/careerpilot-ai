# Step 14 — Target Companies Notion database (visual list + persistent token store)

**Status:** finalized, queued, **not started.**
**Priority:** P2 — nothing is broken; today's setup works, it just requires editing a git-ignored
local file and loses its discovered-token cache on every GitHub Actions run.
**Depends on:** Step 6 (`discover_tokens()`, done); the DuckDuckGo search-fallback tier landed
2026-07-29 (`scripts/sources.py`'s `_dork_candidate_slugs()`, `config/settings.py`'s
`ENABLE_ATS_TOKEN_SEARCH_FALLBACK`).
**Size:** M.

---

## The problem

Two related gaps in today's `TARGET_COMPANIES` setup:

1. `config/profile.json`'s `target_companies` is a plain array in a git-ignored local file —
   growing it means hand-editing JSON, and the file doesn't exist at all from a phone or from a
   fresh CI checkout (mirrors the exact motivation `docs/backlog/step-11-forkable-setup.md`
   already used for de-personalizing tracked files).
2. `config/ats_tokens.json` (the discovered-token cache `discover_tokens()` reads/writes) is also
   git-ignored (`.gitignore:27`). Every GitHub Actions nightly run starts it empty, so
   `discover_tokens()`'s `max_new_probes=20`/run budget re-probes from zero instead of compounding
   across runs. This applies regardless of *how* a token gets discovered — today's
   slug-guess-plus-search-fallback (shipped 2026-07-29), or Step 13's proposed URL-harvest — since
   both write through the same local cache.

This is the same shape of problem Step 12 already solved for the restricted-sponsorship-companies
list: a Notion database as the durable, visually-editable point of truth, with the local/hardcoded
value kept only as a fallback/escape-hatch (`get_restricted_sponsorship_companies()` in
`scripts/utils.py` is the pattern to mirror).

## Binding decisions

1. **Scope to the curated target-company list only** — not the full `discover_tokens()` seed union
   (`TARGET_COMPANIES ∪` every company ever scraped, hundreds of rows). Mirroring the whole union
   to Notion means hundreds of low-value rows and heavy write volume for companies the user never
   deliberately chose. The Notion DB holds only the companies worth adding by hand; the broader
   auto-discovered tail keeps using the local-only cache exactly as today.
2. **Same optional/no-op-if-unset pattern** as every other Notion side-database
   (`NOTION_TARGET_COMPANIES_PAGE_ID`) — a missing id doesn't break anything;
   `TARGET_COMPANIES` in `config/profile.json` stands as the fallback, merged the same way
   `get_restricted_sponsorship_companies()` merges its Notion list with
   `RESTRICTED_SPONSORSHIP_COMPANIES`.
3. **Notion is the source of truth for token results, for rows that exist there.** The local JSON
   cache stays as a same-run/offline mirror for those companies, not the authority — Notion wins on
   conflict.
4. **Absorbs Step 13's deferred "Mirroring the registry to Notion" item** — same target, narrower
   scope (the curated list, not the full harvested registry). Step 13's own Phase 1
   (harvest-from-apply-URL) is unaffected and can still land independently; whichever mechanism
   resolves a token for a company that has a Target-Companies-DB row, the result is written through
   the sync path this story adds.

## Files

- **`scripts/provision_notion.py`** — `TARGET_COMPANIES_PROPERTIES` (`Company` title,
  `Greenhouse`/`Lever`/`Ashby` rich_text, `Last Checked` date); create the DB in `provision()`;
  print its id in `main()`'s add-to-.env block.
- **`config/settings.py`** — `NOTION_TARGET_COMPANIES_PAGE_ID = os.environ.get(...)`, optional.
- **`scripts/utils.py`** — `get_target_companies_from_notion()` (read names, same shape as
  `get_restricted_companies_from_notion()`); `get_ats_tokens_from_notion()` (read into the
  `{company: {greenhouse, lever, ashby, checked}}` shape `_load_tokens()` already uses);
  `upsert_ats_token_to_notion(company, gh, lv, ab, checked)` (create-or-update a row by title
  match). All try/except-safe, no-op on an unset id or any read/write failure.
- **`scripts/sources.py`** — `discover_tokens()`: seed set becomes
  `TARGET_COMPANIES ∪ get_target_companies_from_notion()`; token read/write for companies with a
  Notion row goes through Notion (local JSON stays as the cache for the wider union, as today).
- **`.env.example`** — add `NOTION_TARGET_COMPANIES_PAGE_ID=`.
- **`CLAUDE.md`** — new subsection mirroring "Restricted-sponsorship company list (Notion-managed,
  Step 12)"; update the Notion database schema list and the env-sourced-optional-settings list.
- **New: `tests/test_target_companies_notion.py`** — mocked-Notion read/upsert round-trip,
  merge-with-fallback behavior, no-op-when-unset.

## Real-world step this needs (not code)

Share a new Notion database with the integration — either via `python run.py --init` re-running
provisioning, or created by hand with the schema above and the env var set — same onboarding step
as the other three optional Notion databases (Scratch Pad, Restricted Sponsorship Companies).

## Verification

1. `pytest -v` green including the new test file — no network, no API keys.
2. With `NOTION_TARGET_COMPANIES_PAGE_ID` unset: behavior is byte-for-byte identical to today (pure
   fallback to `config/profile.json`'s `target_companies`).
3. With it set: add a company row in Notion by hand, confirm the next `discover_tokens()` run picks
   it up as a seed, and on a token hit, writes the result back into that row (visible in Notion,
   not just local JSON).
4. Confirm a token discovered for a Target-Companies-DB company survives a simulated "fresh
   checkout": delete local `config/ats_tokens.json`, re-run `discover_tokens()` for that company,
   confirm it's read back from Notion instead of re-probed from scratch.

---

## Related

`docs/refinement-plans/auto-apply/sourcing-bottleneck-analysis.md` — the research trail this story
came out of: recovering a LinkedIn job's real apply URL was found to require an authenticated
LinkedIn session at every turn (rejected); the DuckDuckGo search-fallback (shipped 2026-07-29) and
this Notion persistence layer are what got built instead, aimed at the actual underlying need
(discovering and durably storing which ATS a target company uses) without touching LinkedIn.
