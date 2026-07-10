# TODO: Collapse Stage 1 dedup into a single Notion snapshot

Status: **Implemented.** (Doc was revised after a code review of the original draft; see
*Corrections* below. Verified against the live Notion DB: 250 rows read in 3 paginated calls,
1.53 s.)

## Context

Stage 1's duplicate check is an **N+1 query**. `_pre_filter()` (`scripts/stage1_scrape.py:472`)
calls `db_find_job_by_url(url)` at line 510, and each call runs a full paginated Notion HTTP query
(`db_find_job_by_url` at `scripts/utils.py:449` → `_query_db` at `scripts/utils.py:429`).

Per run, `TARGET_ROLES` holds **5 roles** (`config/settings.py:13`) × 2 sources × 25 listings
(`LINKEDIN_MAX` / `INDEED_MAX`) = **250 raw listings**. The dedup check sits **last** in the filter
chain, so only listings that survive the company / title / location / sponsorship / applicant
filters ever reach it — realistically **~100–175 sequential Notion round-trips**, each ~200–400 ms,
against Notion's ~3 req/s rate limit. That is roughly a minute of pure serial latency per run, plus
429 throttling risk.

The in-run `seen_urls` set (`stage1_scrape.py:536`) only dedups *within* the current run, so it
cannot replace the Notion lookup, which guards against jobs stored by **previous** runs.

**Fix:** read the whole jobs DB once into an in-memory URL set at the start of the scrape loop, and
make `_pre_filter()` do a set-membership test. Dedup requests drop from ~150 to `ceil(rows / 100)`
— a handful of paginated reads.

Semantics are unchanged: both the old per-job filter and the new unfiltered read span **all**
statuses, so a job previously marked `Disregard` still counts as a duplicate and is not re-added.

## Corrections to the original draft

The first version of this doc was directionally right but prescribed two changes that would have
broken or bloated the implementation. Both are fixed below:

1. **Do NOT remove the `db_find_job_by_url` import.** The draft claimed it was "no longer
   referenced" once `_pre_filter` stopped calling it. That is false — it is still called at
   `stage1_scrape.py:397` inside `ingest_interested_from_notion()`. Dropping it from the import
   raises `NameError` on every Stage 1 run.
2. **No snapshot CSV.** The draft specified writing the rows to
   `output/.cache/notion_jobs_snapshot.csv` and deleting them in a `finally` at the end of the same
   run. Nothing ever reads that file back — the rows already live in `existing_jobs` in memory for
   the entire run. The CSV, the `.cache` directory, the `try`/`finally` cleanup, the
   `_write_notion_snapshot_csv()` helper, and the `import csv, os` line are all dropped. The
   in-memory set is the whole fix.

The draft also described the cost as "one query per raw listing → 100+". The per-listing framing is
wrong (dedup is last in the chain), though the ~100+ magnitude happens to hold.

## Decisions

- **Dedup source of truth:** a single in-memory `existing_urls: set`, no on-disk artifact.
- **`ingest_interested_from_notion()` stays as-is.** It runs *before* the snapshot is taken (the
  snapshot must include freshly-promoted rows), and "Interested" rows are typically few. It keeps
  using `db_find_job_by_url` per page.

## Changes

### 1. `scripts/utils.py` — add a full-DB snapshot helper

`_page_to_job()` (line 266) does not include `Status`, so add a small snapshot reader rather than
reuse it directly. Add near the other `db_*` helpers (after `db_get_jobs`, ~line 538):

```python
def db_get_all_jobs() -> list[dict]:
    """Fetch ALL rows from the Notion jobs DB in a few paginated reads (no filter).
    Each dict: page_id, title, company, location, url, status, ats_score.
    Returns [] on failure — dedup then falls back to per-run seen_urls only."""
    try:
        pages = _query_db()  # no filter → all rows, follows pagination
    except Exception as e:
        log(f"[db_get_all_jobs] warning: {e}")
        return []
    jobs = []
    for p in pages:
        props = p.get("properties", {})
        jobs.append({
            "page_id":   p["id"],
            "title":     _notion_plain_text(props.get("Job Title")),
            "company":   _notion_plain_text(props.get("Company")),
            "location":  _notion_plain_text(props.get("Location")),
            "url":       _prop_url(props, "Job URL"),
            # NOTE: Notion returns {"select": None} for a blank Status, so the inner
            # `or {}` is required — .get("select", {}) only defaults on a MISSING key.
            "status":    ((props.get("Status") or {}).get("select") or {}).get("name") or "",
            "ats_score": _prop_number(props, "ATS Match Score"),
        })
    return jobs
```

- Reuses existing `_query_db()` (line 429), `_notion_plain_text()` (358), `_prop_url()` (255),
  `_prop_number()` (258). `_query_db()` already follows `has_more`/`next_cursor` pagination, so the
  whole DB comes back in a handful of reads.
- Only `url` is load-bearing for dedup; the other fields are cheap and make the helper reusable.

### 2. `scripts/stage1_scrape.py` — snapshot once, dedup in memory

**Imports (line 26):** add `db_get_all_jobs`. **Keep `db_find_job_by_url`** — still used at line 397.

**`_pre_filter()` (line 472):** add an `existing_urls: set` parameter and replace the
`db_find_job_by_url(url)` block (lines 510–512) with an in-memory check:

```python
if url in existing_urls:
    counters["duplicate"] += 1
    return False
```

Keep it **last** in the chain so the cheap local filters still short-circuit first and the drop-log
reason ordering is unchanged.

**`run()` (line 518):** take the snapshot *after* `ingest_interested_from_notion()` (line 531), so
freshly-promoted "Interested" rows are already in the DB and get picked up:

```python
# 8a-bis. One-shot Notion snapshot for dedup (replaces per-job db_find_job_by_url)
existing_jobs = db_get_all_jobs()
existing_urls = {j["url"] for j in existing_jobs if j["url"]}
log(f"  Notion snapshot: {len(existing_urls)} existing job URL(s)")
```

Update the `_pre_filter(...)` call site (line 552) to pass `existing_urls`:
`if _pre_filter(job, seen_urls, existing_urls, counters, drop_fh):`

No `try`/`finally` and no cleanup step — there is nothing on disk to clean up.

## Behavior / edge cases

- **Fallback:** if `db_get_all_jobs()` fails it returns `[]`, so `existing_urls` is empty and only
  the in-run `seen_urls` dedups. A failed full read means Notion is unreachable, in which case the
  subsequent `db_add_job()` writes fail too — so there is no silent duplicate flood.
- **URL matching** stays exact-string, identical to the old `{"url": {"equals": url}}` filter.
- **Memory** is a non-issue: a job tracker holds hundreds of rows, not millions.
- **Pre-existing redundancy (leave alone):** `run()` line 549 already tests
  `job["url"] in seen_urls` before calling `_pre_filter`, which makes the identical check at line
  483 unreachable. Out of scope — do not touch it in this change.
- Net Notion calls for dedup drop from ~100–175 to the handful of paginated reads in
  `db_get_all_jobs()`.

## Files to modify

- `scripts/utils.py` — add `db_get_all_jobs()`.
- `scripts/stage1_scrape.py` — import, `_pre_filter` signature + in-memory check, `run()` snapshot.

## Verification

1. `python run.py --setup` — config still loads.
2. `python run.py --stage 1` — confirm in the log:
   - exactly one `Notion snapshot: N existing job URL(s)` line, with N matching the tracker's row
     count;
   - jobs already in Notion are counted under `duplicate:` in the summary and are **not** re-added;
   - no `[db_find_job_by_url] warning:` spam, and no Notion 429s.
3. Confirm the ingest path still works: add a Notion row with `Status = Interested` + a Job URL, run
   `python run.py --ingest`, and verify it promotes to `Scraped`. This exercises the
   `db_find_job_by_url` call at line 397 that the original draft would have deleted.
4. Re-run `python run.py --stage 1` back-to-back. The second run should add 0 new jobs and report
   every listing as a duplicate — proving the snapshot sees prior-run rows.
5. Sanity-check request volume: the run should no longer emit one Notion query per surviving listing.
