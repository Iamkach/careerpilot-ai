Tailor your resume for all "Scraped" jobs in Notion that meet the minimum ATS score threshold.

```bash
python workflow.py --task tailor $ARGUMENTS
```

Common usage:
- `/tailor` — tailor all scraped jobs (no score filter)
- `/tailor --min-score 65` — only tailor jobs with ATS ≥ 65
- `/tailor --company "Stripe"` — tailor only Stripe jobs

What this does:
- Fetches all Notion jobs with Status="Scraped" (filtered by min-score if set)
- Fetches the actual job description via HTTP (not Claude browsing — real fetch)
- Rewrites your resume to match each JD using Claude (ATS keyword optimization)
- Saves tailored resume as `.txt` to `output/resumes/`
- Updates Notion: Status → "Resume Tailored"

Check `output/resumes/` for generated files. Review before applying.

To run with legacy CLI: `python run.py --stage 2 --min-score 65`
