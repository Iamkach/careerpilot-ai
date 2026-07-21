Draft outreach emails (cold or warm referral) for jobs ready to apply.

```bash
python run.py --stage 3 $ARGUMENTS
```

Common usage:
- `/outreach --company "Stripe"` — cold email for Stripe
- `/outreach --company "Google" --contact "Jane Doe" --contact-role "PM"` — warm LinkedIn message

What this does:
- Fetches "Resume Tailored" jobs from Notion (filtered by `--company` if set)
- For warm referral (`--contact` provided): 3-sentence LinkedIn DM, friendly + specific
- For cold email (no contact): short email under 100 words with subject line (JSON)
- Saves drafts to `output/outreach/` — NOT auto-sent (review first)
- Prompts before writing Notion status (manual review by design) — pipe a newline in
  non-interactive contexts: `echo "" | python run.py --stage 3 --company "Stripe"`

After reviewing the drafts in `output/outreach/`, update Notion status manually.
