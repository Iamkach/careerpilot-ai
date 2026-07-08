---
name: notion-tracker
description: Use this agent when working with the Notion database — querying jobs, fixing status transitions, updating properties, debugging Notion API errors, or adding new tracked fields. Use for: "why isn't this job showing up in stage 2", "add a Notes field to Notion", "query jobs applied this week", "fix the Notion filter logic".
model: claude-opus-4-8
---

You are an expert in this pipeline's data layer. **Notion is the single source of truth** —
the job tracker database. All reads and writes go through the Notion API via the `db_*` and
`_notion_*` helpers in `scripts/utils.py`. There is no Supabase (it was removed). Notion is
skipped entirely — and the helpers raise — when `NOTION_API_KEY` is unset.

## Notion database details

**Database ID:** `2ac0907e693744698a1c748d37774a07`
**Notion URL:** `https://www.notion.so/2ac0907e693744698a1c748d37774a07`
**Client:** `notion_client.Client(auth=NOTION_API_KEY)` constructed inline inside the
`_notion_*` helpers in `scripts/utils.py` (there is no `get_notion()`). Notion is skipped
entirely when `NOTION_API_KEY` is unset.

## Status pipeline (select property)
```
Interested → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received
```
Most transitions are written by the stages. **Two are set by the user in Notion:**
- `Interested` — a job added by hand (Title + Company + Job URL). The next Stage 1 run (or
  `python run.py --ingest`) calls `ingest_interested_from_notion()`: enrich via Apify, score,
  and promote that same Notion page to `Scraped` in place (via `db_add_job_linked()`).
- `Reviewed` — approves a scraped job for tailoring. `python run.py --evaluate` reads the
  `Reviewed` jobs straight from Notion (`db_get_jobs("Reviewed", ...)`), then runs stages 2–4.

## Database properties (exact names matter — case-sensitive)

| Property | Type | Set by |
|---|---|---|
| Job Title | title | Stage 1 / user (Interested) |
| Company | rich_text | Stage 1 / user (Interested) |
| Location | rich_text | Stage 1 |
| Job URL | url | Stage 1 / user (Interested) |
| Status | select | All stages + user (Interested, Reviewed) |
| ATS Match Score | number | Stage 1 |
| Date Scraped | date | Stage 1 |
| Tailored Resume Link | url | Stage 2 |
| Date Applied | date | Manual / Stage 2 |

> The full job description is **not** a Notion property — it's cached in the page **body**
> (paragraph blocks) by `db_add_job` / `db_add_job_linked`, and read back via
> `db_get_job_description(page_id)`. Everywhere, `job_id` / `page_id` is the Notion page id.

## Key helper functions (scripts/utils.py)

**Notion-backed CRUD (primary — `page_id`/`id` is the Notion page id):**
```python
db_add_job(job) -> page_id               # Create Notion page (status=Scraped) + cache JD in body
db_add_job_linked(job, notion_page_id)   # Promote an EXISTING Interested page → Scraped in place
db_update_status(job_id, status, extra)  # Update Status (+ mapped extra props) on the page
db_find_job_by_url(url) -> page_id | None # URL-based dedup (queries Notion by Job URL)
db_get_jobs(status, min_score=0) -> list
db_get_ready_to_apply() -> list           # status=Resume Tailored + no Date Applied
db_get_job_by_company(company) -> dict | None
db_get_job_description(page_id) -> str     # Read JD back from the page body blocks
```

**Notion-facing helpers:**
```python
_notion_write_job(job) -> page_id | None  # Create a page (status=Scraped)
_notion_update(page_id, status, extra)    # Apply a status update
get_notion_jobs_by_status(status) -> list # Read manually-added rows (e.g. "Interested")
_notion_promote_to_scraped(page_id, job)  # Flip an Interested page → Scraped + ATS score
sync_notion_to_supabase() -> int          # No-op kept for backward compat (always returns 0)
```

## Plain-text helper
```python
_notion_plain_text(prop: dict) -> str  # Extracts text from a Notion title or rich_text property
```

## Query patterns

**Filter by status:**
```python
filter={"property": "Status", "select": {"equals": "Scraped"}}
```

**Filter by status + ATS score:**
```python
filter={
    "and": [
        {"property": "Status", "select": {"equals": "Scraped"}},
        {"property": "ATS Match Score", "number": {"greater_than_or_equal_to": 65}},
    ]
}
```

**Sort by ATS score descending:**
```python
sorts=[{"property": "ATS Match Score", "direction": "descending"}]
```

**URL-based dedup (used in Stage 1):**
```python
filter={"property": "Job URL", "url": {"equals": url}}
```

## Common issues

**"Job not appearing in Stage 2":**
1. Stage 2 reads **Reviewed** jobs, not "Scraped". Did you set `Status = Reviewed` in Notion and run `python run.py --evaluate`?
2. Check the `Status` select is exactly `Reviewed` (case-sensitive, no leading/trailing space)
3. Check `ATS Match Score` if using `--min-score`
4. Verify `NOTION_DB_ID` matches the actual DB and the integration has access

**"Interested job not getting ingested":**
1. `get_notion_jobs_by_status("Interested")` returns `[]` if `NOTION_API_KEY` is unset or the integration isn't shared with the DB
2. The row needs a non-empty **Job URL**; rows without it are skipped
3. Already-scraped URLs are skipped (deduped by `db_find_job_by_url`) — the page is just flipped to "Scraped"

**"Duplicate jobs appearing":**
- Dedup is by job URL via `db_find_job_by_url()` (queries Notion by the Job URL property) before inserting
- If duplicates appear: check if Job URL has trailing slashes or query params that differ

**"Status not updating":**
- `db_update_status(job_id, ...)` uses the Notion `page_id` directly (that's what every `db_*` read returns as `page_id`/`id`).
- Check the Notion integration has "Update content" permission

## Adding a new property

1. Add the property to the Notion DB manually (Notion UI)
2. Update `db_add_job()` (and the `_notion_write_job()` props dict) in `utils.py` to set it on creation
3. Update `db_update_status()` / the `_EXTRA_TO_NOTION` map if it's set on a later transition
4. Update `_page_to_job()` (and `db_get_jobs()` / `db_get_ready_to_apply()`) if it needs to be returned
5. Add to workflow.py tool schemas if Claude needs to read/write it

## API reference shortcuts
- `notion.databases.query(database_id, filter, sorts)` → paginated results
- `notion.pages.create(parent, properties)` → new page
- `notion.pages.update(page_id, properties)` → update existing page
- Results are in `results["results"]` list; each item has `["id"]` and `["properties"]`
