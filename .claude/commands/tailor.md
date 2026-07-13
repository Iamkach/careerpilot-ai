Tailor your resume for all "Reviewed" jobs in Notion that meet the minimum ATS score threshold.

```bash
python run.py --stage 2 $ARGUMENTS
```

Common usage:
- `/tailor` — tailor all reviewed jobs (no score filter)
- `/tailor --min-score 65` — only tailor jobs with ATS ≥ 65

(Stage 2 filters only by `--min-score`; there's no per-company filter — it always runs against every "Reviewed" job above the threshold.)

What this does:
- Fetches all Notion jobs with Status="Reviewed" (filtered by min-score if set)
- Fetches the actual job description via HTTP (real fetch, not Claude browsing)
- Rewrites your resume to match each JD using Claude (ATS keyword optimization)
- Saves tailored resume as `.docx` + `.txt` to `output/resumes/`
- Updates Notion: Status → "Resume Tailored"

Check `output/resumes/` for generated files. Review before applying.
