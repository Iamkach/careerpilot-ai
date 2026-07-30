# Auto-apply: the real bottleneck is sourcing, not fill automation

*See [`../README.md`](../README.md) for how this relates to the other auto-apply plans.*

**Status (2026-07-29): analysis only, no action taken.** Written to capture a conversation that
re-evaluated whether to build `ashby-workday-custom-fill.md` and/or `browser-extension-prefill.md`
next. Nothing below has been applied to config, code, or the other two docs — this is a snapshot
for the user to re-look at and decide from.

## The question asked

Two things: (1) per-ATS Playwright adapters for Ashby/Workday look like an ongoing maintenance
treadmill — should we just build the browser extension instead and let it cover everything? (2) is
the underlying goal (a job-search pipeline where most applications are pre-filled, not hand-typed)
actually achievable given what the tracker looks like today?

## What was measured (2026-07-29, via a now-deleted throwaway spike)

A live Apify probe of both keyword-search actors (20 fresh listings each) plus a check of what an
unauthenticated LinkedIn job page actually contains:

| Source | Apply-URL field populated | Points somewhere fillable? |
|---|---|---|
| LinkedIn (`valig~linkedin-jobs-scraper`) | **0 / 20** across `applyUrl`, `applyLink`, `companyApplyUrl`, `externalApplyLink`, `link` | n/a — field never exists |
| Indeed, `followApplyRedirects: False` (today's config) | 3 / 20 `externalApplyLink` | **0** — all `indeed.com` wrappers |
| Indeed, `followApplyRedirects: True` | 4 / 20 `externalApplyLink` | 4 real, but **zero** Greenhouse/Lever/Ashby/Workday — all custom Phenom-style career sites (`careers.cisco.com`, `careers.baptisthealth.net`, `careers.massmutual.com`) |

Corrects an earlier claim made in this analysis: `scripts/sources.py:186`'s `job.get("applyUrl")`
fallback for LinkedIn is **dead code**, not a discarded signal — the actor never returns that
field. And it's not recoverable after the fact either: an unauthenticated fetch of a LinkedIn job
page returns a ~344 KB guest page with sign-in/join-now/captcha markers and zero apply-URL
occurrences. The destination is structurally unobtainable for a LinkedIn-sourced row, at scrape
time or later.

The Indeed finding is real but narrow: `followApplyRedirects: True` does recover an external link
on ~20% of listings, at a measured ~+64% wall-clock cost (33.0s → 54.1s / 20 items) against
`_apify_run()`'s 400s poll budget (which raises rather than returning a partial dataset — so the
flag can't be flipped without also raising Indeed's poll count). But every recovered link pointed
at a **custom career site**, never a mainstream ATS.

## Why the tracker is thin on ATS rows — the actual mechanism, not a guess

Today: 1 Greenhouse row out of 508 tracked jobs (413 LinkedIn / 90 Indeed / 4 unknown). Checked
`config/settings.py` directly rather than assuming this is a scraping shortfall:

```python
TARGET_COMPANIES = _profile.get("target_companies", ["Stripe", "Notion", "Figma"])
```

`scripts/sources.py`'s `discover_tokens()` probes Greenhouse/Lever/Ashby board tokens for exactly
this list, union'd at runtime with every company already in Notion. But "companies already in
Notion" are overwhelmingly companies *found via LinkedIn/Indeed keyword search* — a different
population than companies that happen to self-host on those three ATSes. So the board crawler has
almost nothing to crawl. **This is the mechanical root cause**, not a scraper bug and not evidence
that ATS-hosted jobs are rare in the market — the seed list is just three companies.

`ENABLED_SOURCES` already includes `"greenhouse"`, `"lever"`, `"ashby"` (`config/settings.py:64`).
No source is disabled; the pipeline simply isn't being told which companies to look at.

## Is the intent achievable?

Yes, for a meaningful slice of the pipeline — but not through the auto-apply subsystem, and not
through either of the two parked refinement plans. Once real Greenhouse/Lever/Ashby rows exist,
`scripts/autoapply_browser.py` (already shipped, Phases 1–2) fills them; nothing new needs to be
built for that path. The unachievable part stays unachievable regardless of what gets built next:
LinkedIn Easy Apply is both ToS-prohibited to automate and, now confirmed, technically opaque even
for read-only purposes — no amount of engineering recovers an apply URL that was never returned.

## Recommendation reached (not yet applied)

**Don't build the extension now.** Its one architecturally-suited case — custom career sites — is
real but thin: ~20% of 90 Indeed rows, roughly 18 jobs, ever, under today's sourcing mix. Building
a new HTTP bridge + Chrome extension (new language, new local server, new token-auth surface) to
serve ~18 jobs is a poor trade against the alternative below.

**Build instead, in order:**

1. **Grow `TARGET_COMPANIES`** with companies known to self-host on Greenhouse/Lever/Ashby. Zero
   code — a config/`config/application_profile.json`-wizard-scale change. Highest leverage
   available: this is the one lever that can actually shift the fillable-channel distribution,
   because `discover_tokens()` and the existing board crawl already do the rest.
2. **Delete the dead `scripts/sources.py:186` `applyUrl` fallback** for LinkedIn — small
   correctness cleanup now that it's confirmed unreachable, not a feature question.
3. **Re-measure after (1)** before deciding anything about the extension or Ashby/Workday
   adapters. If Greenhouse/Lever/Ashby volume rises and custom-career-site volume (via Indeed)
   stays material *relative to it*, the extension's case gets stronger on real numbers instead of
   a guess.

**Recommendation on the two existing plans (not applied):**

- `docs/refinement-plans/auto-apply/ashby-workday-custom-fill.md` — candidate for deletion, not
  just parking. Nothing measured supports an Ashby or Workday adapter specifically; both Options A
  and B are bets on volume that isn't there and isn't likely to appear from today's sourcing mix
  either. Keeping it filed as "not started, not queued" invites picking it up later just because
  it's already spec'd.
- `docs/refinement-plans/auto-apply/browser-extension-prefill.md` — keep, but its trigger should
  be rewritten once more: re-gated on custom-career-site volume *after* step 1 above, not on the
  raw posting-host split it currently cites.

## Addendum (2026-07-29): can the external apply URL be recovered at all, by any method?

Follow-up research question: is the "structurally unobtainable" conclusion above really final, or
does *some* tool/technique out there return the real destination for a LinkedIn-sourced job? Web
research only — nothing below was tested against a live account or wired into the pipeline.

**Every option that actually returns the field requires an authenticated LinkedIn session.** There
is no public/keyless path that has it — this matches, and explains, the earlier spike's finding.

| Option | Returns external apply URL? | Mechanism | Cost/risk |
|---|---|---|---|
| Public "guest" endpoint (today's approach, both Apify keyword actors) | **No** — field absent from the payload entirely | Unauthenticated fetch | n/a |
| Other Apify LinkedIn actors checked (`apimaestro/linkedin-job-detail`, `curious_coder`, others) | Unverified/no — the one with documented output (`apimaestro`) only exposes `is_easy_apply`, no destination URL; others advertise an `applyUrl` field but their own sample output ships it blank | Same guest-endpoint scraping under the hood | $3–5/1k, but buys nothing new |
| "Job Scraper for LinkedIn" Chrome extension | Claims yes (Greenhouse/Lever/Workday + ATS name) | Undocumented — likely reads the *logged-in* member-facing DOM per page you manually visit, not a bulk/API call | Manual, one job page at a time; no batch/automation path found in its own docs |
| Authenticated Voyager API (e.g. `linkedin-api` PyPI package, formerly `tomquirk/linkedin-api` — that GitHub repo now 404s, name apparently reused/removed) | **Yes, confirmed in source** | `Linkedin(username, password)` logs in with a real account, gets a session cookie, then `get_job(job_id)` calls `/jobs/jobPostings/{job_id}`. LinkedIn's own Voyager/Apply-Connect schema names the offsite-apply destination `companyApplyUrl` under `applyMethod` — present for authenticated requests, absent for guest ones. This is exactly the extra data an authenticated session unlocks. | Package's own README: *"might violate LinkedIn's Terms of Service. Use it at your own risk."* Needs a real account's credentials in the pipeline, and account ban is the downside if detected — not a form-fill ToS violation like Easy Apply automation, but still a ToS-adjacent scraping violation, and losing the account is worse than a blocked scrape. |
| Vendor-run authenticated scraping (Bright Data, Unipile, linkedapi.io's "account-based" method) | Yes, same mechanism | Same authenticated-session trick, outsourced — the vendor supplies/rotates the LinkedIn account and eats the ban risk instead of you | $/request or subscription; still indirectly ToS-adjacent, just insulated behind a vendor |
| "Legal 2026 alternatives" enrichment platforms (PDL, Bright Data's contact product, Kaspr, Surfe, Apollo.io) | No | Built for contact/email enrichment, not job-posting apply destinations | Not applicable to this problem |

## Recommendation on the addendum (not applied)

Confirms rather than overturns the original conclusion: recovering the real destination is
possible in principle, but only by authenticating as a LinkedIn member — either your own account
(direct ToS/ban risk) or a paid vendor account (cost, and the same risk one layer removed). That's
a materially different, heavier commitment than "flip a flag on the existing Apify actor," and it
doesn't fit this pipeline's read-only, keyless-where-possible posture. Given the volume math in
the original analysis (LinkedIn rows are 413/508 tracked jobs, but the ATS thinness is a
`TARGET_COMPANIES` seeding problem, not a missing-field problem), **still not worth building**.
Revisit only if the `TARGET_COMPANIES` fix (step 1 above) is done, ATS-native volume is measured,
*and* it's still too low relative to LinkedIn volume to hit application throughput goals — at that
point an authenticated-session vendor (not a self-hosted account) would be the way to reconsider
this, to keep the ban risk off the user's own LinkedIn account.

## Follow-up implemented (2026-07-29): search-fallback ATS token discovery

The addendum's real target wasn't "recover the LinkedIn apply link" for its own sake — it was
token discovery: knowing which Greenhouse/Lever/Ashby token a company uses at all, so
`discover_tokens()`'s board crawl (see "Multi-source sourcing" in `CLAUDE.md`) has something to
seed beyond `TARGET_COMPANIES`. A live re-check (fetching the `jobs-guest/jobs/api/jobPosting/{id}`
endpoint real scrapers use, against 5 fresh job IDs including two Notion postings) confirmed the
destination URL is walled behind LinkedIn's sign-in prompt even there — so the addendum's
conclusion holds: no keyless path recovers it through LinkedIn.

But token discovery doesn't need LinkedIn at all. `discover_tokens()` today makes exactly one
slug guess (`_slugify(company)`) and permanently misses any company whose real token doesn't match
its display name. Implemented a keyless fallback instead: when the direct guess misses for a given
ATS, `_dork_candidate_slugs()` (`scripts/sources.py`) runs a DuckDuckGo HTML search for
`site:{ats domain} "{company}"` and extracts candidate slugs from the result URLs; each candidate
is still verified through the same `_probe_greenhouse`/`_probe_lever`/`_probe_ashby` functions as
the direct guess before being accepted — the search only proposes, the ATS API still verifies, so
this adds no new unverified-trust surface. Gated behind `ENABLE_ATS_TOKEN_SEARCH_FALLBACK`
(`config/settings.py`, default on) as an escape hatch if DuckDuckGo starts blocking/rate-limiting.
See `CLAUDE.md`'s "Multi-source sourcing" section for the shipped description, and
`tests/test_ats_token_search_fallback.py` for coverage.

This resolves this file's addendum without touching LinkedIn or its ToS — the
`TARGET_COMPANIES`-seeding recommendation from the original analysis is unaffected and still
stands as the other lever for growing ATS-native volume.

## What was NOT done

No authenticated LinkedIn session was ever set up or tested — that path was researched and
rejected. No changes to the other two refinement-plan docs.
