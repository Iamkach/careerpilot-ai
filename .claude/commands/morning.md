Run the full morning job search pipeline (stages 1–4): scrape LinkedIn → score with ATS → tailor resumes → generate digest.

```bash
python workflow.py
```

This runs the Claude agentic workflow which orchestrates all stages automatically. Claude will:
1. Scrape LinkedIn jobs for your target roles and city
2. Score each job against your resume (ATS match %)
3. Tailor your resume for jobs scoring above the threshold
4. Generate an HTML digest of ready-to-apply jobs

Check `output/digest_{date}.html` when complete.

Arguments: $ARGUMENTS
If arguments provided, append them: `python workflow.py $ARGUMENTS`
