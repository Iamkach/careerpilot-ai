Verify the pipeline setup — check API keys, dependencies, and output directories.

```bash
python run.py --setup
```

This checks:
- Python dependencies installed for the active provider(s) — including a split `FAST_PROVIDER`/`QUALITY_PROVIDER`
- API keys set as environment variables (never as literals in `config/settings.py`)
- config/resume.txt exists and is non-empty
- output/ directories can be created
- Current `Retry` queue size (jobs whose AI scoring failed, awaiting re-score)

If anything fails, the error message will tell you exactly what to fix.

**Quick setup checklist:**
1. Edit `config/settings.py` — fill in YOUR_NAME, YOUR_EMAIL, YOUR_BIO, TARGET_ROLES, TARGET_COMPANIES, ENABLED_SOURCES
2. Set API keys as env vars: ANTHROPIC_API_KEY, APIFY_API_TOKEN, NOTION_API_KEY (HUNTER_API_KEY optional, Step 7 spike only)
3. Add your resume text to `config/resume.txt`
4. Add the `Retry` status option to the Notion DB's `Status` select once (the API can't create it)
5. Run `/setup` to verify
6. Run `/scrape` to start the pipeline

**Install dependencies:**
```bash
pip install -r requirements.txt
```
