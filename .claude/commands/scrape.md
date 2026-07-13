Scrape LinkedIn jobs for your target roles, score them against your resume, and save to Notion.

```bash
python run.py --stage 1 $ARGUMENTS
```

What this does:
- Calls Apify's `curious_coder/linkedin-jobs-scraper` for each role in TARGET_ROLES
- Scores each job against your resume using Claude (0–100 ATS match score)
- Deduplicates via Job URL before inserting
- Saves new jobs to Notion with Status="Scraped"

Check Notion tracker after completion. Jobs need status "Scraped" before stage 2 can run.
