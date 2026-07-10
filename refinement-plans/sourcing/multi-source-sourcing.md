# Multi-source job sourcing, real freshness, and cross-source dedup (baseline: `feat/maverick` @ `54ad4fc`)

**the LinkedIn payload mismatch is real rather than an artifact of incomplete actor docs. Confirming that needs a live run against one role with the dataset items inspected. Worth doing before anyone acts on the plan.**

## Context

Stage 1 currently scrapes exactly two sources — LinkedIn and Indeed, both via Apify actors hardcoded into `scripts/stage1_scrape.py`. Inspired by HyperAgent's "scout aggressively across every source" copilot, we want to widen sourcing substantially.

Three structural gaps block simply bolting on more scrapers:

1. **No posted-date exists anywhere in the codebase.** Freshness is delegated entirely to the LinkedIn actor's `timePosted:"past24Hours"` param. The Indeed payload (`stage1_scrape.py:157-165`) sends **no date param at all**, despite its docstring claiming "posted in the last day" — so Indeed returns arbitrarily old listings today. A freshness rule isn't even expressible.
2. **Dedup is exact-URL only.** The same Stripe job arrives as a LinkedIn URL, an Indeed URL, *and* a Greenhouse URL. Adding sources multiplies duplicates rather than adding coverage.
3. **Sources are hardcoded**, so each new one means editing `run()`.

Additionally, `TARGET_COMPANIES` (`config/settings.py:15`) is defined but referenced nowhere — dead config that turns out to be exactly the input an ATS-board crawler needs.

**Outcome:** nine sources behind a registry, a real `posted_date` enforced end-to-end, and dedup that collapses the same job across sources — with the ATS copy (canonical direct-apply URL, full JD) winning.

### Verified before planning

All three ATS APIs were probed live. They are free, unauthenticated, and expose true posted dates:

| Source | Endpoint | Date field | JD field |
|---|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `first_published` | `content` (HTML) |
| Lever | `api.lever.co/v0/postings/{token}?mode=json` | `createdAt` (epoch ms) | `descriptionPlain` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{token}` | `publishedAt` (ISO) | `descriptionPlain` |

Greenhouse also returns `company_name`, which is the only usable verification signal during token discovery. Lever and Ashby return none.

**These boards are not keyword-searchable** — you fetch a company's entire board and filter titles client-side. That is why they need a company list, and why they get a different function signature from the keyword sources.

### User decisions

- **Freshness:** `MAX_JOB_AGE_DAYS = 14`, keep undated jobs (`DROP_UNDATED_JOBS = False`). Enforced only when a date is known. Matches the codebase's existing "keep unknowns" philosophy (`is_us_location` returns `True` on blank).
- **Dedup:** company + title fingerprint. Accepts collapsing two genuinely distinct same-title reqs at one company.
- **Scope:** all nine sources — LinkedIn, Indeed, Greenhouse, Lever, Ashby, **plus** Glassdoor, Wellfound, Welcome-to-the-Jungle (Otta), Built In. This overrides the recommendation to stop at the three ATS boards; see *Risks* for what that buys and costs.
- **Notion:** add `Posted Date`, `Source`, `Applicant Count`, `Salary Range`.

---

## Architecture

```
TARGET_COMPANIES ─┐
                  ├─→ token registry (probe + cache: config/ats_tokens.json)
Notion companies ─┘        │
   (from the dedup         │
    snapshot, free)        ↓
                    BOARD_SOURCES (company-keyed, free JSON)
                      greenhouse · lever · ashby
                              │
TARGET_ROLES ─→ KEYWORD_SOURCES (role-keyed, Apify)
                  linkedin · indeed · glassdoor
                  wellfound · wttj · builtin
                              │
                              ↓
                    normalize → posted_date
                              ↓
                    cross-source collapse  (fingerprint; ATS URL wins)
                              ↓
                    _pre_filter  (+ new freshness check)
                              ↓
                    score_jobs_batch → db_add_job → Notion
```

`_pre_filter`, `score_jobs_batch`, and `db_add_job` keep their signatures. The winning job still has exactly one URL, so everything downstream is unchanged.

---

## Phase 1 — Foundation (all free, no Apify credits)

### 1a. `scripts/sources.py` (new)

One module, not a package — five-to-nine small functions don't justify fragmenting an otherwise flat `scripts/*.py` tree, and the shared normalization helpers belong in one place. Move `_apify_run`, `_parse_salary`, `scrape_linkedin`, `scrape_indeed` out of `stage1_scrape.py` into it.

**Shared output contract** — every source returns a list of:

```python
{
  "url": str, "title": str, "company": str, "location": str,
  "description": str,
  "source": str,                # "linkedin" | "greenhouse" | ...
  "posted_date": str | None,    # ISO "YYYY-MM-DD", or None if unknown
  "applicant_count": int | None,
  "salary_range": str,
}
```

**Two registries, because the two families are keyed differently:**

```python
def linkedin_source(role: str, max_results: int) -> list[dict]: ...
KEYWORD_SOURCES = {"linkedin": ..., "indeed": ...}

def greenhouse_source(company: str, token: str) -> list[dict]: ...
BOARD_SOURCES = {"greenhouse": ..., "lever": ..., "ashby": ...}
```

Board sources fetch the whole board and keep only titles passing a new `title_matches_targets(title) -> bool` (token match against `TARGET_ROLES`).

Every Apify keyword source is `_apify_run(actor, payload)` + a field map, so make that declarative — it's what makes Phase 2 cheap:

```python
APIFY_SOURCES = {
    "linkedin": {"actor": "bebity~linkedin-jobs-scraper", "payload": _linkedin_payload, "map": _map_linkedin},
    "indeed":   {"actor": "bebity~indeed-scraper",        "payload": _indeed_payload,   "map": _map_indeed},
}
```

New in `config/settings.py`:

```python
ENABLED_SOURCES   = ["linkedin", "indeed", "greenhouse", "lever", "ashby"]
MAX_JOB_AGE_DAYS  = 14
DROP_UNDATED_JOBS = False
```

### 1b. Cross-source dedup

Build the fingerprint set from the **same** `db_get_all_jobs()` snapshot stage 1 already takes (`stage1_scrape.py:540`) — it returns `company` and `title` per row, so this costs **zero extra Notion reads**:

```python
existing_fps = {job_fingerprint(j["company"], j["title"]) for j in existing_jobs if j["company"] and j["title"]}
```

```python
def job_fingerprint(company: str, title: str) -> str:
    return f"{_norm_company(company)}|{_norm_title(title)}"
```

`_norm_company` lowercases, strips legal suffixes (`inc|llc|ltd|corp|co|the`) and non-alphanumerics → `"Stripe, Inc." → "stripe"`.
`_norm_title` lowercases, drops `(Remote)`/`(Hybrid)`/`(US)` parentheticals, drops trailing `" - Remote"` / `", San Francisco"` clauses, drops req IDs, maps roman numerals to arabic → `"Software Engineer II (Remote)" → "software engineer 2"`.

**Seniority and level tokens are deliberately kept.** "Software Engineer", "Senior Software Engineer", and "Software Engineer II" are different reqs with different comp bands; stripping them would cause real false merges. Roman→arabic normalization only makes levels consistent across sources.

**Location is deliberately excluded.** It is the most source-divergent field ("San Francisco, CA" vs "San Francisco" vs "Remote"), so including it would defeat cross-source merging — the entire point of the change. The accepted cost is that two genuinely distinct same-title reqs at one company collapse to one row. For a personal tracker that is defensible: they're interchangeable to an applicant, and you don't want fifty Google "Software Engineer" rows. Merging across *different* companies cannot happen, since company is in the key and normalization only strips legal suffixes ("Stripe" and "Stripe Press" stay distinct).

**Collapse happens before `_pre_filter`**, on the gathered `raw_jobs`:

```python
SOURCE_PRIORITY = {"greenhouse": 0, "lever": 1, "ashby": 2, "linkedin": 3,
                   "glassdoor": 4, "wellfound": 5, "wttj": 6, "builtin": 7, "indeed": 8}
```

Lower wins. ATS boards are the employer's canonical posting: direct-apply URL, full untruncated JD, real posted date. Collapsing first means the sponsorship regex and freshness check run against the *fullest* JD — filtering first could drop a good Greenhouse copy on a truncated-JD false trigger and keep an inferior Indeed copy.

Then inside `_pre_filter`, extend the existing duplicate check:

```python
if url in existing_urls or job_fingerprint(company, title) in existing_fps:
    counters["duplicate"] += 1
    return False
```

**`run()` restructures** from per-role incremental scoring to: global gather → collapse → filter → score. Necessary because a duplicate can span both roles *and* sources, so per-role processing structurally cannot see it.

**Latent bug to fix while here:** `db_get_all_jobs()` returns `[]` on failure. Today that silently means "no duplicates" and re-adds everything; with nine sources it would mass-duplicate the tracker. Distinguish "empty DB" from "read failed" and abort the scrape on failure.

### 1c. Freshness, end to end

Per-source date extraction:

- **Greenhouse → `first_published`** (fall back to `updated_at` only when null). `updated_at` bumps on any JD or title edit, which would make a stale req look fresh — the opposite of what freshness means.
- **Lever → `createdAt`** (epoch ms → ISO).
- **Ashby → `publishedAt`**.
- **LinkedIn** → first present of `postedAt`/`publishedAt`/`postedDate`; parse relative strings ("2 days ago") best-effort. Often absent, but the actor query already constrains to 24h.
- **Indeed** → `postingDateParsed`/`date` if present, else `None`.

New check in `_pre_filter`, placed **immediately after the `seen_urls` check and before `is_skipped_company`** — it's a cheap comparison with a high drop rate, so failing fast there avoids the expensive JD sponsorship regex downstream:

```python
if not _is_fresh(job.get("posted_date")):   # None ⇒ fresh, unless DROP_UNDATED_JOBS
    counters["stale"] += 1
    _log_drop(drop_fh, "stale", job)
    return False
```

Add `stale` to the `counters` dict and the run summary; the drop-log infrastructure (`_log_drop`) needs no changes.

**Fix the Indeed date bug** by sending the actor's max-age param. Verify the exact key against the actor's input schema first (some Indeed actors use `maxDaysOld`, others Indeed's native `fromage` of 1/3/7/14). Treat the actor param as a coarse pre-filter and the client-side `_is_fresh` check as the real backstop.

### 1d. ATS board-token discovery

`discover_tokens(companies) -> dict` in `sources.py`. For each company: `slugify(company)` → probe Greenhouse, Lever, Ashby → cache hits **and** misses to `config/ats_tokens.json` (co-located with config, user-editable and committable, unlike volatile `output/`):

```json
{"Stripe": {"greenhouse": "stripe", "lever": null, "ashby": null, "checked": "2026-07-09"}}
```

Re-probe an all-null entry only if `checked` is older than ~30 days, so a company that later adopts an ATS is picked up.

**Slug collisions are a real risk and unequal by source.** Greenhouse is verifiable — reject unless `jobs[0].company_name` normalized-matches the target. Lever and Ashby expose no company field, so they cannot be fully verified automatically. Mitigate by: accepting only exact normalized slug matches, requiring the board to be non-empty with ≥1 title matching `TARGET_ROLES`, **logging every auto-accepted Lever/Ashby token loudly on first discovery**, and letting the user pin or veto a token by hand in `ats_tokens.json`. This limitation should be stated in the log, not hidden.

**Seed companies:** `TARGET_COMPANIES` ∪ the distinct `company` values already in the `db_get_all_jobs()` snapshot. This is a bootstrapping loop — LinkedIn/Indeed discover *which companies exist*, and the ATS boards then give you depth, freshness, and canonical URLs for those companies, free.

**Volume:** first run is `(companies × 3)` probes — ~55 companies → ~165 requests, once. Thereafter near-zero. Sleep 0.3–0.5 s between probes and cap new-company probes per run (e.g. 20) to amortize discovery. No API key, so no billing or secret exposure.

### 1e. Notion schema

**Manual migration first — this is the highest-risk step of the change.** `notion.pages.create` fails hard on a property key that doesn't exist. Because `_notion_write_job` (`utils.py:300`) catches everything and returns `None`, a schema mismatch surfaces as `db_add_job` raising a vague failure for *every job* — a total scrape outage with no diagnosable cause. Making the writes conditional on non-empty values does **not** save you, because Notion rejects unknown property *keys* regardless of value.

Add these to the tracker DB **before** deploying the writer change:

| Property | Type | Why |
|---|---|---|
| `Posted Date` | date | Makes the freshness rule visible and auditable |
| `Source` | rich_text | Which source the winning copy came from |
| `Applicant Count` | number | Already collected, currently discarded |
| `Salary Range` | rich_text | Already collected, currently discarded |

`Source` is **rich_text, not select** — a select value that isn't a pre-created option throws on write, and given the bare `except`, that would silently zero out every scrape.

Then extend `_notion_write_job` to write all four. Note it currently accepts `applicant_count` and `salary_range` from `db_add_job` (`stage1_scrape.py:587-596`) and **silently drops them on the floor**; this fixes that. Also **make `_notion_write_job` log the real Notion exception** instead of swallowing it, so a schema mismatch is diagnosable.

The Interested-intake path (`ingest_interested_from_notion` → `_notion_promote_to_scraped`) sets `source="manual"`, `posted_date=None`, and continues to bypass all filters, freshness included.

---

## Phase 2 — Breadth (Apify, opt-in, one at a time)

Actors exist for all four, several from `bebity` — the same vendor as the current LinkedIn/Indeed actors. Once the `APIFY_SOURCES` table from 1a exists, each is a payload builder + a field map, roughly 15 lines.

Ship them **one at a time, disabled by default**, appended to `ENABLED_SOURCES` only after validation. Before writing the field map for each, run the actor once with `maxItems=3` and dump the raw item keys — write the mapping against real output rather than a guessed schema. (This mirrors the "research spike first" advice already recorded in `plan/reliability-filtering-networking.md` §3.)

| Source | Note |
|---|---|
| Glassdoor | `bebity~glassdoor-jobs-scraper` exists; exposes a posting-age filter. Best of the four. |
| Built In | ~50k US tech jobs; keyword/remote/experience filters. Good US coverage. |
| Wellfound | Startup-weighted. Actors advertise anti-detect browsers to bypass DataDome/Cloudflare — see *Risks*. |
| Welcome to the Jungle | **Otta merged into WTTJ**; `otta.com` is gone. WTTJ is Europe-weighted, so US yield will likely be thin. Validate coverage before investing in the mapping. |

Cross-source dedup (1b) is what makes this safe to do at all — without it, four more sources would quadruple tracker noise instead of adding coverage.

---

## Files

| File | Change |
|---|---|
| `scripts/sources.py` | **New.** Both registries, all source fns, `APIFY_SOURCES` table, `job_fingerprint`/`_norm_*`, `slugify`/`discover_tokens`, `SOURCE_PRIORITY`, `title_matches_targets`, `_apify_run` (moved) |
| `scripts/stage1_scrape.py` | Restructure `run()` to gather → collapse → filter → score; add freshness check + `stale` counter to `_pre_filter`; import from `sources.py` |
| `scripts/utils.py` | Extend `_notion_write_job` with the four new props; stop swallowing the Notion exception; guard `db_get_all_jobs()` read-failure |
| `config/settings.py` | Add `ENABLED_SOURCES`, `MAX_JOB_AGE_DAYS`, `DROP_UNDATED_JOBS`; `TARGET_COMPANIES` becomes the board seed |
| `config/ats_tokens.json` | **New.** Discovered token map (hits + misses + TTL), user-editable |
| `workflow.py` | `run_scrape` tool description (line ~204) still says "LinkedIn + Indeed" — copy only, no logic change |
| `CLAUDE.md` | Update the Notion schema list, the Stage 1 description, and the Stage 1 Filters section |

---

## Verification

1. **ATS sources, no side effects.** Call `greenhouse_source("Stripe", "stripe")` directly and confirm the returned dicts match the output contract with a real ISO `posted_date`. Repeat for Lever and Ashby against a known board.
2. **Token discovery.** Run `discover_tokens(["Stripe", "Notion", "Figma", "Acme Nonexistent"])`; confirm `config/ats_tokens.json` records hits and misses, that the Greenhouse `company_name` check rejects a mismatch, and that auto-accepted Lever/Ashby tokens are logged loudly.
3. **Dedup, offline.** Unit-test `job_fingerprint` on the real divergence cases: `("Stripe, Inc.", "Software Engineer II (Remote)")` vs `("Stripe", "Software Engineer II")` must match; `"Senior Software Engineer"` vs `"Software Engineer"` must **not**; `"Stripe"` vs `"Stripe Press"` must **not**.
4. **Freshness.** With `MAX_JOB_AGE_DAYS=14`, confirm a Greenhouse job with `first_published` 30 days ago is dropped with reason `stale` in `output/filter_logs/`, and that an undated Indeed job survives (`DROP_UNDATED_JOBS=False`). Flip `DROP_UNDATED_JOBS=True` and confirm it now drops.
5. **Notion schema, before the writer change.** Add the four properties by hand, then run `python run.py --stage 1` with a small `maxItems`. Confirm rows carry `Posted Date`, `Source`, `Applicant Count`, `Salary Range`. Deliberately rename one property in Notion and confirm the *new* error surfacing reports the real Notion exception rather than a silent zero-job run.
6. **End-to-end cross-source merge.** Enable `linkedin, indeed, greenhouse` for a company known to post to all three. Confirm exactly one Notion row appears and its `Job URL` is the Greenhouse `absolute_url`, with `Source = "greenhouse"`.
7. Re-run stage 1 immediately and confirm **zero** new rows (fingerprint dedup holds across runs).

---

## Risks and out of scope

**Workday is out of scope.** No universal public API — every tenant has its own host with undocumented per-tenant CxS endpoints behind anti-bot, and dates arrive as relative text ("Posted 3 Days Ago"). Tenant discovery is far harder than an ATS slug lookup. High effort, brittle, poor date reliability — exactly the properties this change is trying to eliminate.

**"Use the browser to dig past listing walls" is out of scope.** Brittle selectors, high maintenance, and it burns browser CU for the worst date reliability of any option. The ATS boards give us the full JD for free; there is no wall left worth digging past.

**Phase 2 carries costs Phase 1 does not:**

- **Apify spend.** These actors bill roughly $1 per 1,000 results. Nine sources × 5 roles × 25 items ≈ 500 items/run ≈ $0.50/run — around **$15/month on a daily schedule**, well beyond the free ~5 CU tier. Phase 1 adds zero cost; Phase 2 is where the meter starts.
- **ToS posture.** Glassdoor and Wellfound prohibit scraping, and the Wellfound actors explicitly advertise anti-detect browsers to bypass DataDome and Cloudflare. Using them means adopting that posture through a third party. That is a knowing choice for a personal job search, and a good reason to keep these sources opt-in and off by default rather than shipped enabled.
- **Yield may not justify either.** WTTJ is Europe-weighted; Wellfound is startup-weighted. Validate real US result counts on a single run before wiring up the full field mapping for each.

The three ATS boards are free, unauthenticated, stable, and carry real dates and full JDs. Phase 1 is where the value is concentrated; Phase 2 is genuinely additive but earns its keep only if the yield checks out.
