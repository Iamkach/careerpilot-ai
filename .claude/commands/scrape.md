Scrape jobs for your target roles across all enabled sources, score them against your resume, and save to Notion.

```bash
python run.py --stage 1 $ARGUMENTS
```

What this does:
- Re-scores any jobs stuck in `Status="Retry"` from a previous failed scoring pass first (cached JD, no repeat Apify call)
- Ingests any Notion `Status="Interested"` rows (manual intake) — same as `--ingest`
- Gathers listings from every `ENABLED_SOURCES` entry (`config/settings.py`):
  - `linkedin`, `indeed` — Apify actors, searched per `TARGET_ROLES`
  - `greenhouse`, `lever`, `ashby` — free keyless board APIs, crawled per `TARGET_COMPANIES`
- Deduplicates via Job URL **and** company+title fingerprint (catches the same job posted to multiple sources — keeps the ATS-board copy over LinkedIn/Indeed)
- Filters by freshness (`MAX_JOB_AGE_DAYS`), company/title denylist, sponsorship, and `MIN_ATS_SCORE`
- Scores each survivor against your resume using Claude (0–100 ATS match score, sponsorship, company_type) in one batched call
- A job whose scoring call fails is written as `Status="Retry"` instead of a fabricated score
- Saves new jobs to Notion with Status="Scraped"

Check Notion tracker after completion. Jobs need status "Scraped" before stage 2 can run.
