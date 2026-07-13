Generate a comprehensive interview prep guide for a specific role.

```bash
python run.py --stage 5 $ARGUMENTS
```

Required arguments: `--company "CompanyName" --role "Role Title"`

Example:
- `/interview --company "Meta" --role "Senior PM"`
- `/interview --company "Stripe" --role "PM" --jd-file "output/jds/stripe_pm.txt"`

What this does:
- Uses Claude to research the company, role expectations, and likely interview format
- Generates an HTML prep guide covering:
  - Company background + recent news
  - Role-specific competencies to demonstrate
  - Likely behavioral questions (STAR format prompts)
  - Technical/case questions for the role
  - Questions to ask the interviewer
- Saves to `output/prep_guides/{company}_{role}_prep.html`

Open the HTML file in a browser for a formatted guide. Review 24–48 hours before your interview.
