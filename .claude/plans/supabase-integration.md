# Supabase Integration

Supabase is the primary programmatic data store (SQL, no rate limits).
Notion stays as the visual tracker — writes mirror to both.

## SQL schema (run once in Supabase SQL Editor)

```sql
CREATE TABLE jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_title               TEXT NOT NULL,
    company                 TEXT NOT NULL,
    job_url                 TEXT UNIQUE NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'Scraped'
                            CHECK (status IN (
                                'Scraped','Resume Tailored','Applied',
                                'Outreach Sent','Interview Scheduled','Offer Received'
                            )),
    date_scraped            DATE NOT NULL DEFAULT CURRENT_DATE,
    ats_match_score         NUMERIC(5,2),
    tailored_resume_link    TEXT,
    date_applied            DATE,
    hiring_manager          TEXT,
    hiring_manager_linkedin TEXT,
    notion_page_id          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX jobs_status_score_idx ON jobs (status, ats_match_score DESC);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_updated_at
BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

## Architecture

- **Reads**: always Supabase (SQL, indexed, fast)
- **Writes**: Supabase first, then Notion mirror if `NOTION_API_KEY` is set
- Notion is optional — if key is empty, mirror writes are silently skipped

## New public functions in utils.py

| Function | Purpose |
|---|---|
| `db_find_job_by_url(url)` | Dedup check — returns Supabase id or None |
| `db_add_job(job)` | Insert to Supabase + mirror to Notion |
| `db_update_status(job_id, status, extra_props)` | Update Supabase + mirror to Notion |
| `db_get_ready_to_apply()` | Status="Resume Tailored" AND date_applied IS NULL |
| `db_get_jobs(status, min_score)` | Filter by status + ATS score |
| `db_get_job_by_company(company)` | Full job dict by company name (stage 5/6) |

## Install

```bash
pip install supabase
```

`notion-client` stays installed for mirror writes.
