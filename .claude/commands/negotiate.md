Research salary benchmarks and generate a negotiation script for an offer.

```bash
python run.py --stage 6 $ARGUMENTS
```

Required arguments: `--company "CompanyName" --role "Role Title" --offer AMOUNT`

Example:
- `/negotiate --company "Stripe" --role "PM" --offer 185000`
- `/negotiate --company "Google" --role "Senior PM" --offer 220000`

What this does:
- Uses Claude to research salary benchmarks for the role/company/location
- Analyzes your offer vs. market rates (Levels.fyi, Glassdoor ranges)
- Generates an HTML negotiation guide with:
  - Market rate analysis
  - Counter-offer recommendation with rationale
  - Word-for-word negotiation script
  - Email template for written counter
  - Common pushbacks + how to handle them
- Saves to `output/prep_guides/{company}_{role}_negotiate.html`

Open the HTML file in a browser. Have it ready before your negotiation call.
