Generate the morning digest of jobs ready to apply, sorted by ATS match score.

```bash
python workflow.py --task digest $ARGUMENTS
```

Common usage:
- `/digest` — generate HTML digest, print to terminal
- `/digest --send` — also send via Gmail (requires OAuth setup)

What this does:
- Fetches all Notion jobs with Status="Resume Tailored" and no Date Applied
- Sorts by ATS match score (highest first)
- Generates clean HTML digest with job table + action suggestions per ATS tier:
  - ≥80: High match — apply directly today
  - ≥60: Good match — apply + warm outreach
  - ≥40: Moderate — apply, consider adjacent angle
  - <40: Lower match — apply to adjacent roles first
- Saves HTML to `output/digest_{date}.html`
- Optionally emails via Gmail

Gmail setup (for --send): requires `config/gmail_credentials.json` from Google Cloud Console OAuth.

To run with legacy CLI: `python run.py --stage 4` or `python run.py --stage 4 --send`
