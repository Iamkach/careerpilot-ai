Run the full morning job search pipeline (stages 1, 4): scrape LinkedIn → score with ATS → generate review digest.

```bash
python run.py $ARGUMENTS
```

This scrapes and stops at a review digest — the two-step daily flow:
1. Scrape LinkedIn jobs for your target roles, score each against your resume (ATS match %)
2. Generate an HTML review digest of "Scraped" jobs

Check `output/review_digest_{date}.html` when complete. Mark good jobs `Status = Reviewed`
in Notion, then run `/tailor` (`python run.py --evaluate`) to tailor + outreach + digest them.
