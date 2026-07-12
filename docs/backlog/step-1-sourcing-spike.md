# Step 1 — Sourcing spike (resolve C5 and the JobSpy-vs-Apify fork)

**Priority:** P0 — nothing downstream should be written until this returns.
**Depends on:** Step 0
**Blocks:** Step 2 (schema migration should reflect the real source set), Step 6 (re-keys sources
off whatever this decides)
**Size:** S (a few hours)
**Source plan(s):**
[`refinement-plans/sourcing/scraping-sources.md`](../refinement-plans/sourcing/scraping-sources.md)
(full doc is essentially this spike's findings — read it first)

## Context

Four plans (filtering, reliability, multi-source, and the baseline itself) all tune filters,
dedup, and scoring against a Stage-1 listing volume **nobody has measured**. Two confirmed bugs
make the current baseline unknown:

1. `bebity~indeed-scraper` returns HTTP 404 — the actor is deprecated. `scrape_indeed()` swallows
   the exception (`stage1_scrape.py:166-170`), so **every Indeed scrape has silently returned zero
   listings** for the life of the project. Only trace: `✗ Indeed scrape failed` in the log.
2. `bebity~linkedin-jobs-scraper` costs $29.99/month + usage (a paid rental), but
   `_linkedin_payload_base()` sends `queries`/`timePosted`/`scrapeCompany`/`cookie` —
   **`curious_coder`'s payload fields**, not bebity's (`title`/`location`/`publishedAt`/`rows`/
   `workType`). This reads like a migration that changed the actor constant and left the payload
   builder untouched. **LinkedIn's real result volume is unverified.**

## What to do

Run each actor once with `maxItems=3` and inspect the raw dataset item keys directly — don't
assume the schema.

1. Run the current LinkedIn actor (`bebity~linkedin-jobs-scraper`) with the current payload.
   Confirm whether it returns real results or empty/garbage given the field mismatch.
2. Run `valig~linkedin-jobs-scraper` (Option A recommendation: $0.28–0.40/1k, no cookie, returns
   `recruiterName`/`recruiterUrl`/`applicant_count`/`salary_range` — see scraping-sources.md
   Option A) against the same role/query. Compare volume and field coverage.
3. Run `misceres~indeed-scraper` ($3/1k) — the maintained successor whose input schema the
   existing (broken) Indeed payload already near-matches (rename `maxItems` →
   `maxItemsPerSearch`).
4. Decide: **Option A (actor swap: `valig` + `misceres`)** vs. **Option B (JobSpy / ATS boards)**.
   Recommendation in the source doc is hybrid — JobSpy/ATS boards for Step 6, but Step 1 only
   needs to unblock the immediate LinkedIn/Indeed replacement so Steps 2–5 have a working Stage 1
   to build on.
5. Record the decision and the measured baseline (jobs/role/day) in this repo — either as an
   addendum to `scraping-sources.md` or a short note the next stories can cite.

## Acceptance criteria

- [x] Raw dataset item keys captured for all three actor runs (bebity-current, valig, misceres) —
      recorded in `scraping-sources.md`'s "Step 1 spike" addendum, not a committed script.
      bebity's schema was pulled from the Apify API and compared field-for-field rather than
      live-run, since it's a $29.99/mo flat-rate rental — see rationale in the addendum.
- [x] LinkedIn payload/actor mismatch confirmed or refuted with real output. Confirmed total
      (zero overlapping fields) via schema diff; valig live run confirmed as the replacement.
- [x] Indeed 404 confirmed (trivial — the URL alone proves it) and a replacement chosen
      (`misceres~indeed-scraper`).
- [x] Decision recorded: `valig` + `misceres` swap (Option A) — see `scraping-sources.md`
      addendum for the field-mapping differences.
- [x] `config/settings.py` (note only — no actor constants lived there) and
      `scripts/stage1_scrape.py`'s `LINKEDIN_ACTOR`/`INDEED_ACTOR`/`_linkedin_payload_base()`/
      `scrape_indeed()` updated to match the winning actors.
- [x] `python run.py --stage 1`-equivalent (direct `scrape_linkedin()`/`scrape_indeed()` calls,
      `max_results=3`, one role, no Notion writes) produced 3/3 real LinkedIn and 3/3 real
      Indeed listings. A production-volume `python run.py --stage 1` run (all `TARGET_ROLES`,
      writes to Notion) is still needed for the jobs/role/day baseline — not run here since it
      has real side effects on the live tracker; see addendum.

## Out of scope

- JobSpy integration itself (that's Step 6 territory if chosen).
- ATS board sources (Greenhouse/Lever/Ashby) — Step 6.
- Any Notion schema changes — Step 2.

## Open questions this resolves

- **Q2 (C5):** JobSpy vs. Apify actor swap.
- **Q4:** Keep Indeed at all, given zero historical listings?

## Files touched

`scripts/stage1_scrape.py` (actor constants + payload builders only — no structural changes),
`config/settings.py` (actor name constants if applicable).

## References

- Architecture analysis §B.8 risks M1, M2.
- Architecture analysis §C.7 roadmap DAG, Step 1.
- `refinement-plans/README.md` §"Step 1 — Sourcing spike" and Conflict C5.
