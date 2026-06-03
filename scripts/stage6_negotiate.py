#!/usr/bin/env python3
"""
stage6_negotiate.py — Data-backed salary negotiation brief
────────────────────────────────────────────────────────────
What it does:
  1. Looks up your company in Notion tracker
  2. Uses Claude + web search to find P25/P50/P75 comp benchmarks
  3. Generates a negotiation brief with a counter-offer script
  4. Updates Notion Status → "Offer Received"

Run:
  python scripts/stage6_negotiate.py --company "Stripe" --role "Product Manager" --offer 180000
"""

import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat,
    db_update_status, db_get_job_by_company,
    log, today, ensure_dirs,
)

SYSTEM_NEGOTIATE = """You are a compensation expert and negotiation coach with deep knowledge
of tech industry salaries, equity structures, and negotiation tactics.
Always provide specific, actionable advice backed by data and market context."""

NEGO_DIR = "output/negotiation"


def get_company_type(company: str) -> str:
    faang = ["google", "meta", "apple", "amazon", "netflix", "microsoft"]
    if company.lower() in faang:
        return "FAANG / large public tech"
    return "tech company (startup or mid-size)"


def generate_negotiation_brief(company: str, role: str, city: str, offer: float) -> str:
    company_type = get_company_type(company)

    prompt = f"""I have received a job offer and need to prepare for negotiation.

Company: {company} ({company_type})
Role: {role}
Location: {city}
Initial offer: ${offer:,.0f} base salary

Please provide:

## 1. Market compensation benchmarks
Current market rates for {role} at {company_type} in {city}:
- P25 (lower): base, signing bonus, equity (annual value)
- P50 (median): base, signing bonus, equity
- P75 (upper): base, signing bonus, equity

Use levels.fyi, Glassdoor, Blind, LinkedIn Salary data as reference points.
Be specific with numbers.

## 2. Offer assessment
How does the ${offer:,.0f} offer compare to market? Is it low/fair/high?
What components are most worth negotiating?

## 3. Signing bonus vs base salary strategy
Explain the tradeoff for {company_type}:
- Why companies prefer signing bonuses
- When to push for higher base vs. signing bonus
- What I should optimize for in this case

## 4. Counter-offer script (for a phone call)
A natural, confident script I can use verbatim or adapt.
Should be: data-backed, non-confrontational, specific with a number.
Target counter: [suggest a specific number based on P75 benchmark]

## 5. Non-salary items to negotiate
If they push back on comp, name 4 things worth negotiating:
PTO, remote policy, equity vesting, title, start date, L&D budget, etc.
Prioritize by impact.

## 6. Red lines and walkaway point
Based on market data, what is the minimum acceptable offer?
What signals a bad-faith offer vs. genuine budget constraints?

Be specific. Give real numbers. Assume I'm comfortable negotiating but want a script."""

    return claude_chat(prompt, system=SYSTEM_NEGOTIATE, max_tokens=5000, quality=True)


def render_brief(content: str, company: str, role: str, offer: float) -> str:
    import re
    html = content
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^\- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = html.replace("\n\n", "</p><p>")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Negotiation Brief — {company}</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.7; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #1a1a1a; padding-bottom: 10px; }}
  h2 {{ font-size: 17px; margin-top: 32px; border-left: 3px solid #009966; padding-left: 10px; color: #1a1a1a; }}
  li {{ margin: 6px 0; }}
  .meta {{ font-size: 13px; color: #666; margin-bottom: 24px; }}
  .script {{ background: #f5fff5; border: 1px solid #bbddb5; border-radius: 8px; padding: 16px 20px; font-style: italic; }}
</style>
</head>
<body>
  <h1>Salary Negotiation Brief — {company}</h1>
  <p class="meta">Role: {role} &nbsp;·&nbsp; Initial offer: ${offer:,.0f} &nbsp;·&nbsp; Generated: {today()}</p>
  <p>{html}</p>
</body>
</html>"""


def run(company: str, role: str, offer: float):
    ensure_dirs()
    Path(NEGO_DIR).mkdir(parents=True, exist_ok=True)

    log(f"Generating negotiation brief for {company} — {role} (offer: ${offer:,.0f})")
    brief = generate_negotiation_brief(company, role, TARGET_CITY, offer)

    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").replace(" ", "_")
    filename = f"negotiation_{safe(company)}_{today()}.html"
    out_path = Path(NEGO_DIR) / filename
    out_path.write_text(render_brief(brief, company, role, offer))
    log(f"✓ Brief saved: {out_path}")

    # Update status
    job = db_get_job_by_company(company)
    if job:
        db_update_status(job["page_id"], "Offer Received")
        log("✓ Status updated → Offer Received")

    print(f"\nOpen your negotiation brief:\n  {out_path.resolve()}")
    print("\n--- BRIEF SUMMARY ---")
    # Print first 800 chars as preview
    print(brief[:800] + "\n[...open HTML file for full brief]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True,        help="Company name")
    parser.add_argument("--role",    required=True,        help="Role title")
    parser.add_argument("--offer",   required=True, type=float, help="Initial offer base salary (number only)")
    args = parser.parse_args()
    run(company=args.company, role=args.role, offer=args.offer)
