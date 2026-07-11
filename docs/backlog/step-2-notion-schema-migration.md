# Step 2 — Batched Notion schema migration + writer error-surfacing

**Priority:** P0 — removes the single riskiest step ("add a Notion property") from four later
stories by doing it once, up front.
**Depends on:** Step 1
**Blocks:** Step 3, Step 4, Step 5, Step 6 (all write to properties this step creates)
**Size:** S
**Source plan(s):** all five plan docs touch `_notion_write_job()`; this story consolidates their
overlapping asks per `refinement-plans/README.md` Conflict **C7**.

## Context

`_notion_write_job()` (`scripts/utils.py:300-320`) has a bare `except Exception: return None`. A
schema mismatch — a missing or mistyped Notion property — collapses into `db_add_job()` raising
`RuntimeError("Notion page creation failed")`, which reads as a total scrape outage with **no
diagnosable cause**. Four separate plans each independently propose adding properties and fixing
this same bug (C7). Landing it once, first, means nobody rewrites nobody else's fix.

## Current behavior

- `_notion_write_job()` hardcodes `"Status": {"select": {"name": "Scraped"}}` (line 312) — no
  caller can write a different status.
- `if job.get("ats_score"):` (line 315) is a truthiness check that silently discards a genuine
  score of `0`.
- The bare `except` (lines 319-320) swallows the real Notion exception.
- `applicant_count` / `salary_range` are already collected in Stage 1 (`stage1_scrape.py:144-145`)
  and passed to `db_add_job` (`:594-595`), but `_notion_write_job` has no matching property and
  drops them on the floor (R8 in the risk register).

## What to do

### 1. Add every new Notion property by hand, in the tracker DB, before any writer code changes

| Property | Type | Consumed by |
|---|---|---|
| `Sponsorship` | select — `yes` / `no` / `unknown` | Step 4/5 |
| `Scoring Attempts` | number | Step 5 |
| `Status` — add option | *(decide the name — see Open questions)* | Step 5 |
| `Posted Date` | date | Step 6 |
| `Source` | **rich_text**, not select | Step 6 |
| `Applicant Count` | number | Step 6 (already collected, currently discarded) |
| `Salary Range` | **rich_text**, not select | Step 6 |

`Source` and `Salary Range` must be rich_text: a select value that isn't a pre-created option
throws on write, and given the bare `except`, that would silently zero out every scrape.

### 2. Fix `_notion_write_job()` (`scripts/utils.py`)

- Accept a caller-supplied status: `job.get("status") or "Scraped"`.
- Change `if job.get("ats_score"):` → `if job.get("ats_score") is not None:`.
- Write `Sponsorship`, `Scoring Attempts`, `Posted Date`, `Source`, `Applicant Count`,
  `Salary Range` when present in `job`.
- Replace the bare `except Exception: return None` with one that **logs the real Notion
  exception** (status code + message) before returning, so a future mismatch is diagnosable
  instead of silent.
- Degrade gracefully for `Sponsorship` specifically (per the filtering plan §7): catch a 400 on
  that property, retry the create once without it, and log a warning — this only matters if
  someone forgets step 1's manual migration for that one property.

### 3. Fix `_notion_promote_to_scraped()` and `_page_to_job()`

- `_notion_promote_to_scraped()` (`utils.py:400-423`): take a `status="Scraped"` parameter, write
  `Sponsorship`, apply the same `is not None` ATS fix.
- `_page_to_job()` (`utils.py:266-282`): add a `_prop_select()` reader beside the existing
  `_prop_url`/`_prop_number`/`_prop_date`, surface `sponsorship` and `scoring_attempts` in the
  returned dict.

### 4. Update `CLAUDE.md`

Add the new properties to the "Notion database schema" list once they're live and read/written by
code (do this incrementally as Steps 4–6 land, not all at once here — but note the schema section
needs updates coming).

## Acceptance criteria

- [ ] All 6 properties above exist in the live Notion tracker DB with the correct types.
- [ ] `_notion_write_job()` accepts and writes a caller-supplied `status`.
- [ ] `ats_score == 0` is written correctly (verify with a manual test job scored at 0).
- [ ] A deliberately-broken write (rename one property temporarily) produces a **logged, specific**
      error — not a blanket `RuntimeError` with no detail — and the write still succeeds for
      `Sponsorship` specifically per the graceful-degrade path.
- [ ] `_page_to_job()` round-trips `sponsorship` and `scoring_attempts`.
- [ ] Existing stage runs (`python run.py --stage 1`) are unaffected — no regression in current
      write behavior.

## Out of scope

- Actually populating these fields with real logic (word-boundary matching, retry queue, source
  registry) — that's Steps 4–6. This step only creates the schema and makes the writer safe to
  extend.
- The `Leads` database for Step 7 — a separate, much larger schema (~22 props), created in that
  story.

## Open questions this affects

- **Q1 (C3):** the `Status` option name (`Retry` / `Needs Review` / reuse `Human Review`) must be
  decided before adding it here, or added as a placeholder and renamed later. Recommend deciding
  now since Step 5 needs it and renaming a live select option mid-flight is disruptive.
- **Q7:** whether `Sponsorship = unknown` rows should be visible/actionable in a Notion view —
  decide when building the view, not blocking for this story.

## Files touched

`scripts/utils.py` (`_notion_write_job`, `_notion_promote_to_scraped`, `_page_to_job`), Notion
tracker DB (manual schema edit, not code).

## References

- Architecture analysis §D.1 risk register, R4 (🔴), R8 (🟠).
- `refinement-plans/README.md` Step 2 and Conflict C7.
- `refinement-plans/filtering/stage1-filtering-rework.md` §7-8.
- `refinement-plans/reliability/hybrid-agentic-migration-plan.md` §3e, §5.
- `refinement-plans/sourcing/multi-source-sourcing.md` §1e.
