Draft outreach emails (cold or warm referral) for jobs ready to apply.

```bash
python workflow.py --task outreach $ARGUMENTS
```

Common usage:
- `/outreach --company "Stripe"` — cold email for Stripe
- `/outreach --company "Google" --contact "Jane Doe" --contact-role "PM"` — warm LinkedIn message
- `/outreach` — draft for all "Resume Tailored" jobs

What this does:
- Fetches "Resume Tailored" jobs from Notion
- For warm referral (--contact provided): 3-sentence LinkedIn DM, friendly + specific
- For cold email (no contact): short email under 100 words with subject line (JSON)
- Saves drafts to `output/outreach/` — NOT auto-sent (review first)
- Does NOT auto-update Notion to "Outreach Sent" — you confirm manually

After reviewing the drafts in `output/outreach/`, update Notion status manually or run:
`python run.py --stage 3 --company "Stripe"` (has interactive confirm prompt)

To run with legacy CLI: `python run.py --stage 3 --company "Stripe" --contact "Jane Doe"`
