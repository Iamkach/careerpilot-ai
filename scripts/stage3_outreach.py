#!/usr/bin/env python3
"""
stage3_outreach.py — AI-drafted outreach emails (warm referral + cold)
───────────────────────────────────────────────────────────────────────
What it does:
  1. Fetches "Resume Tailored" jobs from Notion
  2. For each, drafts a warm referral message (if contact known) OR cold email
  3. Saves drafts to output/outreach/ as .txt files
  4. Updates Notion Status → "Outreach Sent" when you confirm

Run:
  python scripts/stage3_outreach.py
  python scripts/stage3_outreach.py --company "Stripe" --contact "Jane Doe at Payments team"
"""

import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat, load_resume,
    db_update_status, db_get_ready_to_apply,
    log, today, ensure_dirs,
)

OUTREACH_DIR = "output/outreach"

SYSTEM_OUTREACH = """You are an expert at writing concise, warm, non-transactional
professional outreach emails. You write like a human, not like a template.
Never use filler phrases like 'I hope this finds you well'."""


# ── Warm referral message ─────────────────────────────────────

def draft_warm_referral(job: dict, contact_name: str, contact_role: str, bio: str) -> str:
    prompt = f"""I'm applying for {job['title']} at {job['company']}.
I know {contact_name} who works there as {contact_role}.

Write me a 3-sentence warm referral request for LinkedIn:
- Friendly and specific, not transactional
- Reference something genuine about {job['company']} or the role
- End with a single, low-friction ask (e.g. 'happy to send my resume')

My background: {bio}

Return only the message text."""
    return claude_chat(prompt, system=SYSTEM_OUTREACH)


# ── Cold email to hiring manager ──────────────────────────────

def draft_cold_email(job: dict, bio: str, hm_name: str = "", hm_context: str = "") -> dict:
    hm_line = f"Hiring manager: {hm_name}. Context: {hm_context}" if hm_name else ""
    prompt = f"""Write a short cold email (under 100 words) for this situation:
- I am applying for {job['title']} at {job['company']}
- {hm_line}
- My background: {bio}

Rules:
- Open with something specific about their work or the company (not generic flattery)
- One sentence about my relevant background
- One clear, low-pressure CTA
- Subject line included

Return JSON: {{"subject": "...", "body": "..."}}"""
    raw = claude_chat(prompt, system=SYSTEM_OUTREACH)
    try:
        import json
        # Strip markdown fences if present
        clean = raw.strip().strip("```json").strip("```").strip()
        return json.loads(clean)
    except Exception:
        return {"subject": f"Interest in {job['title']} at {job['company']}", "body": raw}


# ── Save outreach draft ───────────────────────────────────────

def save_draft(content: str, job: dict, kind: str) -> str:
    path = Path(OUTREACH_DIR)
    path.mkdir(parents=True, exist_ok=True)
    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").strip().replace(" ", "_")
    filename = f"{today()}_{kind}_{safe(job['company'])}_{safe(job['title'])}.txt"
    (path / filename).write_text(content)
    return str(path / filename)


# ── Main pipeline ─────────────────────────────────────────────

def run(target_company: str = None, contact: str = None, contact_role: str = ""):
    jobs = db_get_ready_to_apply()

    if not jobs:
        log("No 'Resume Tailored' jobs found. Run stage2_tailor.py first.")
        return

    # Filter to specific company if requested
    if target_company:
        jobs = [j for j in jobs if target_company.lower() in j["company"].lower()]

    if not jobs:
        log(f"No matching jobs found for company: {target_company}")
        return

    log(f"Drafting outreach for {len(jobs)} job(s)")

    for job in jobs:
        log(f"\n→ {job['company']} — {job['title']}")

        if contact:
            # Warm referral
            draft = draft_warm_referral(job, contact, contact_role, YOUR_BIO)
            file_path = save_draft(
                f"WARM REFERRAL — {job['company']} — {job['title']}\n"
                f"Send to: {contact}\n\n{draft}",
                job, "warm_referral"
            )
            log(f"  ✓ Warm referral drafted → {file_path}")
        else:
            # Cold email
            email = draft_cold_email(job, YOUR_BIO)
            file_path = save_draft(
                f"COLD EMAIL — {job['company']} — {job['title']}\n"
                f"Subject: {email['subject']}\n\n{email['body']}",
                job, "cold_email"
            )
            log(f"  ✓ Cold email drafted → {file_path}")

        # Ask before marking as sent
        confirm = input(f"\n  Mark '{job['company']}' as 'Outreach Sent' in Notion? (y/n): ").strip().lower()
        if confirm == "y":
            db_update_status(job["page_id"], "Outreach Sent")
            log("  ✓ Status updated → Outreach Sent")

    log(f"\nAll drafts saved to ./{OUTREACH_DIR}/")
    log("Review, personalise, and send them yourself.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company",      type=str, default=None, help="Filter to specific company")
    parser.add_argument("--contact",      type=str, default=None, help="Name of referral contact")
    parser.add_argument("--contact-role", type=str, default="",   help="Their role at the company")
    args = parser.parse_args()
    run(target_company=args.company, contact=args.contact, contact_role=args.contact_role)
