Verify the pipeline setup — check API keys, dependencies, and output directories.

```bash
python run.py --setup
```

This checks:
- Python dependencies installed (anthropic, notion-client, requests, etc.)
- API keys set in config/settings.py (non-empty)
- config/resume.txt exists and is non-empty
- output/ directories can be created
- Notion DB connection (basic query test)

If anything fails, the error message will tell you exactly what to fix.

**Quick setup checklist:**
1. Edit `config/settings.py` — fill in YOUR_NAME, YOUR_EMAIL, YOUR_BIO, TARGET_ROLES, TARGET_CITY
2. Add API keys: ANTHROPIC_API_KEY, APIFY_API_TOKEN, NOTION_API_KEY
3. Add your resume text to `config/resume.txt`
4. Run `/setup` to verify
5. Run `/scrape` to start the pipeline

**Install dependencies:**
```bash
pip install anthropic notion-client requests
```
