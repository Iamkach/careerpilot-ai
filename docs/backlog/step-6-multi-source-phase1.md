# Step 6 — Multi-source sourcing, Phase 1 (free ATS boards + cross-source dedup + freshness)

**Priority:** P2 — sourcing breadth; land after reliability is solid so a broken new source fails
loud (via Step 5's error-surfacing) rather than silently.
**Depends on:** Step 5
**Blocks:** Step 7 (benefits from Conflict C6 — an earlier LinkedIn actor swap hands Step 7 free
recruiter contact data)
**Size:** L — new module, registry pattern, `run()` restructure
**Source plan(s):**
[`refinement-plans/sourcing/multi-source-sourcing.md`](../refinement-plans/sourcing/multi-source-sourcing.md)
Phase 1 only (§1a-1e). **Phase 2 (Glassdoor/Wellfound/WTTJ/Built In) is a separate future story —
see Out of scope.**

## Context

Stage 1 scrapes exactly two hardcoded sources. Three structural gaps block adding more:

1. **No posted-date exists anywhere.** Freshness is delegated entirely to the LinkedIn actor's
   `timePosted` param; the Indeed payload sends no date param at all despite its docstring
   claiming "posted in the last day."
2. **Dedup is exact-URL only.** The same job posted to LinkedIn, Indeed, and a company's own
   Greenhouse board arrives as three unrelated rows.
3. **Sources are hardcoded** — each new one means editing `run()` directly.

`TARGET_COMPANIES` (`settings.py:15`) is defined but referenced nowhere — it's exactly the input
an ATS-board crawler needs.

## What to do

### 1. `scripts/sources.py` (new module)

Move `_apify_run`, `_parse_salary`, `scrape_linkedin`, `scrape_indeed` here from
`stage1_scrape.py`. Shared output contract for every source function:

```python
{
  "url": str, "title": str, "company": str, "location": str, "description": str,
  "source": str,                 # "linkedin" | "greenhouse" | ...
  "posted_date": str | None,     # ISO "YYYY-MM-DD", or None if unknown
  "applicant_count": int | None,
  "salary_range": str,
}
```

Two registries (keyword-keyed vs. company-keyed sources are shaped differently):

```python
KEYWORD_SOURCES = {"linkedin": ..., "indeed": ...}
BOARD_SOURCES   = {"greenhouse": ..., "lever": ..., "ashby": ...}
```

Board sources fetch a company's entire board and keep only titles passing
`title_matches_targets(title) -> bool` (token match against `TARGET_ROLES`) — they are not
keyword-searchable.

New in `config/settings.py`:
```python
ENABLED_SOURCES   = ["linkedin", "indeed", "greenhouse", "lever", "ashby"]
MAX_JOB_AGE_DAYS  = 14
DROP_UNDATED_JOBS = False
```

### 2. Cross-source dedup (company + title fingerprint)

Build the fingerprint set from the **same** `db_get_all_jobs()` snapshot Stage 1 already takes —
zero extra Notion reads:

```python
def job_fingerprint(company: str, title: str) -> str:
    return f"{_norm_company(company)}|{_norm_title(title)}"
```

- `_norm_company`: lowercase, strip legal suffixes (`inc|llc|ltd|corp|co|the`), strip
  non-alphanumerics.
- `_norm_title`: lowercase, drop `(Remote)`/`(Hybrid)`/`(US)` parentheticals and trailing
  location/dash clauses, drop req IDs, map roman numerals to arabic. **Keep seniority/level
  tokens** — "Software Engineer" and "Senior Software Engineer" are different reqs and must not
  merge. **Exclude location from the key** — it's the most source-divergent field; the accepted
  cost is two genuinely-distinct same-title reqs at one company collapsing to one row.

Collapse **before** `_pre_filter`, on the gathered `raw_jobs`, with the ATS copy winning:

```python
SOURCE_PRIORITY = {"greenhouse": 0, "lever": 1, "ashby": 2, "linkedin": 3, "indeed": 8}
```

Lower wins — ATS boards are the employer's canonical posting (direct-apply URL, full untruncated
JD, real date), so collapsing first means the sponsorship regex and freshness check run against
the fullest JD available.

Extend `_pre_filter`'s existing dup check:
```python
if url in existing_urls or job_fingerprint(company, title) in existing_fps:
    counters["duplicate"] += 1
    return False
```

`run()` restructures from per-role incremental scoring to: **global gather → collapse → filter →
score** — a duplicate can span both roles and sources, so per-role processing can't see it.

**Fix while here:** `db_get_all_jobs()` returns `[]` on failure today, which silently means "no
duplicates" and re-adds everything. With more sources this would mass-duplicate the tracker.
Distinguish "empty DB" from "read failed" and **abort the scrape on failure** rather than
proceeding.

### 3. Freshness, end to end

Per-source date extraction: Greenhouse → `first_published` (fall back to `updated_at` only when
null — `updated_at` bumps on any edit, which would make a stale req look fresh). Lever →
`createdAt` (epoch ms). Ashby → `publishedAt`. LinkedIn → best-effort from
`postedAt`/`publishedAt`/`postedDate`. Indeed → `postingDateParsed`/`date` if present, else `None`.

New check in `_pre_filter`, placed **immediately after the `seen_urls` check and before
`is_skipped_company`** (cheap, high drop rate — fail fast before the expensive JD regex):

```python
if not _is_fresh(job.get("posted_date")):   # None ⇒ fresh, unless DROP_UNDATED_JOBS
    counters["stale"] += 1
    _log_drop(drop_fh, "stale", job)
    return False
```

Fix the Indeed date bug too, if Indeed is still enabled per Step 1's decision — send the actor's
max-age param (verify the exact key against the actor's real input schema first).

### 4. ATS board-token discovery

`discover_tokens(companies) -> dict` in `sources.py`. For each company: `slugify(company)` → probe
Greenhouse/Lever/Ashby → cache hits **and** misses to `config/ats_tokens.json`:

```json
{"Stripe": {"greenhouse": "stripe", "lever": null, "ashby": null, "checked": "2026-07-09"}}
```

Re-probe an all-null entry only if `checked` is older than ~30 days.

**Slug collisions are a real risk, unequal by source.** Greenhouse is verifiable (reject unless
`jobs[0].company_name` normalized-matches the target). Lever/Ashby expose no company field —
mitigate with exact normalized-slug matches, requiring the board to be non-empty with ≥1 title
matching `TARGET_ROLES`, and **logging every auto-accepted Lever/Ashby token loudly on first
discovery** so the user can pin or veto it by hand.

Seed companies: `TARGET_COMPANIES` ∪ the distinct `company` values already in the
`db_get_all_jobs()` snapshot. First run is `(companies × 3)` probes; cap new-company probes per run
(e.g. 20) and sleep 0.3–0.5s between probes to amortize discovery.

### 5. Notion writer extension

Extend `_notion_write_job` (already made safe in Step 2) to write `Posted Date`, `Source`,
`Applicant Count`, `Salary Range` from the new source dicts.

The Interested-intake path continues to set `source="manual"`, `posted_date=None`, and bypass all
filters including freshness.

## Acceptance criteria

- [ ] `greenhouse_source("Stripe", "stripe")`, `lever_source(...)`, `ashby_source(...)` called
      directly each return dicts matching the output contract with a real ISO `posted_date`.
- [ ] `discover_tokens(["Stripe", "Notion", "Figma", "Acme Nonexistent"])` records hits and misses
      correctly in `config/ats_tokens.json`; the Greenhouse company-name check rejects a mismatch;
      auto-accepted Lever/Ashby tokens are logged loudly.
- [ ] `job_fingerprint` unit-tested on the documented divergence cases: `("Stripe, Inc.",
      "Software Engineer II (Remote)")` vs `("Stripe", "Software Engineer II")` **match**;
      `"Senior Software Engineer"` vs `"Software Engineer"` **do not match**; `"Stripe"` vs
      `"Stripe Press"` **do not match**.
- [ ] With `MAX_JOB_AGE_DAYS=14`: a 30-day-old Greenhouse job is dropped with reason `stale`; an
      undated Indeed job survives (`DROP_UNDATED_JOBS=False`); flipping the flag to `True` now
      drops it.
- [ ] `python run.py --stage 1` with a small `maxItems` produces Notion rows carrying `Posted
      Date`, `Source`, `Applicant Count`, `Salary Range`. Deliberately rename one property and
      confirm the Step-2 error-surfacing reports the real exception, not a silent zero-job run.
- [ ] End-to-end: enable `linkedin, indeed, greenhouse` for a company posting to all three — exactly
      one Notion row appears, `Job URL` is the Greenhouse `absolute_url`, `Source = "greenhouse"`.
- [ ] Re-running Stage 1 immediately produces **zero** new rows (fingerprint dedup holds across
      runs).
- [ ] `db_get_all_jobs()` read failure aborts the scrape instead of proceeding as if the DB were
      empty.

## Out of scope

- **Phase 2** (Glassdoor, Wellfound, Welcome to the Jungle, Built In) — opt-in, one source at a
  time, only after validating real US yield per source. Carries real Apify spend (~$15/mo at daily
  cadence) and, for Glassdoor/Wellfound, a ToS posture the user hasn't signed off on (Open Question
  Q5). Write as a separate story once Phase 1 is stable and the user decides on Q5.
- Workday — no universal public API, out of scope per the source doc's own risk analysis.
- Browser-based scraping to get past listing walls — explicitly rejected in the source doc.

## Files touched

`scripts/sources.py` (new), `scripts/stage1_scrape.py` (restructure `run()`, `_pre_filter`
freshness check), `scripts/utils.py` (`_notion_write_job` extension, `db_get_all_jobs` failure
guard), `config/settings.py` (`ENABLED_SOURCES`, `MAX_JOB_AGE_DAYS`, `DROP_UNDATED_JOBS`,
`TARGET_COMPANIES` becomes live), `config/ats_tokens.json` (new), `workflow.py` (copy-only:
`run_scrape` tool description still says "LinkedIn + Indeed"), `CLAUDE.md`.

## References

- Architecture analysis §C.2, §C.3 (target-state component diagram, ERD), §C.4 (Stage-1 flow).
- `refinement-plans/README.md` Step 6.
- `refinement-plans/sourcing/multi-source-sourcing.md` — full spec; its "Verification" section
  (items 1-7) maps directly onto the acceptance criteria above.
