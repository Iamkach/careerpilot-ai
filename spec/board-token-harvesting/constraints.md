# Constraints

1. **Observation beats verification-by-probe, and the code must record which it had.**
   `config/ats_tokens.json` entries gain a `provenance` field: `"observed"` (parsed out of a real
   posting URL) or `"guessed"` (today's `_slugify()` probe). Greenhouse stays probe-verified either
   way — `_probe_greenhouse()` checks `jobs[0].company_name` and is cheap. Lever and Ashby expose
   no company field, which is exactly why `_probe_lever()`/`_probe_ashby()` log the loud
   `⚠ AUTO-ACCEPTED … unverifiable` warning today. **An observed Lever/Ashby token does not get
   that warning** — it did not come from a guess, so there is nothing for the user to veto.
2. **Never re-guess a company that has an observed token.** `discover_tokens()` currently skips any
   company with ≥1 hit (`:840`) and re-probes all-null entries after 30 days. Add: skip probing
   entirely when `provenance == "observed"`, and let observation overwrite a `"guessed"` token
   (observation is strictly better evidence).
3. **Phase 1 makes zero new network calls.** The harvest reads fields already present in the Apify
   response. This is what keeps it S-sized and makes it safe to land before knowing the hit rate.
4. **Do not follow LinkedIn apply redirects.** LinkedIn's apply link sits behind an authwall;
   resolving it requires an authenticated session — the precise ToS/behavioral-detection surface
   that `FILLABLE_CHANNELS` (`scripts/autoapply.py:106`) excludes LinkedIn from **by rule, not by
   configuration**. This story must not reintroduce it through a side door.
5. **Record boards we cannot crawl.** A Workday/iCIMS URL still answers the question the user
   actually asked — "which board does this company use" — even where no crawlable API exists.
   Recording it is nearly free and is what tells us whether Phase 3 is worth building.
6. **`config/ats_tokens.json` is git-ignored** (`.gitignore:27`). The registry is therefore
   per-fork local state — a fresh clone starts at zero and re-earns its tokens. Accepted for
   Phases 1-3; mirroring to Notion belongs to a separate story.
7. **Harvest ordering in `_scrape_pass()` is load-bearing.** Must run *after* the global gather
   (board-sourced jobs contribute their own URLs as confirmation) and *before*
   `collapse_by_fingerprint()` (which discards the LinkedIn copy of a duplicate in favour of the
   ATS copy — harvesting after the collapse would silently throw away the exact rows this feature
   reads). Tokens harvested this run take effect next run, not this one — that's deliberate.
8. **Back-compat, no migration needed.** Existing cache entries have no `provenance` key.
   `entry.get("provenance", "guessed")` makes every current entry read as a guess, which is
   correct as-is.
