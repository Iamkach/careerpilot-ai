Show the current status of jobs in the Notion pipeline tracker.

Check the live Notion DB for job counts at each stage. Read config and print a summary of pipeline state.

First, read config/settings.py to get NOTION_DB_ID and NOTION_API_KEY. Then check what's in the output/ directory for recent files. Report:

1. **Config check**: Are all required API keys set? Is resume.txt populated?
2. **Output files**: What's in output/resumes/, output/outreach/, output/prep_guides/? List recent files with dates.
3. **Retry queue**: How many jobs are sitting at `Status="Retry"` (failed AI scoring, awaiting the next stage 1 run)? How many are parked at `Status="Human Review"` (sponsorship gate hits)?
4. **Next recommended action**: Based on what's present, what stage should run next?

Also show the pipeline stage commands as a reminder:
- Stage 1 (Scrape): `python run.py --stage 1`
- Stage 2 (Tailor): `python run.py --stage 2 --min-score 65`
- Stage 3 (Outreach): `python run.py --stage 3 --company "CompanyName"`
- Stage 4 (Digest): `python run.py --stage 4`
- Full morning run: `python run.py`
