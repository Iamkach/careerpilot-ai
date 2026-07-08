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
    claude_chat, load_resume, parse_json_response,
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

def draft_cold_emails_batch(jobs: list[dict], bio: str) -> list[dict]:
    """Draft cold emails for all jobs in a single API call.

    Returns a list of dicts [{company, subject, body}, ...] in the same order.
    Falls back to a placeholder for any job that can't be parsed from the response.
    """
    if not jobs:
        return []

    job_list = "\n\n".join(
        f"{i+1}. Company: {j['company']}\n   Role: {j['title']}"
        for i, j in enumerate(jobs)
    )
    prompt = f"""Write a short cold email (under 100 words) for EACH job below.
My background: {bio}

Rules for every email:
- Open with something specific about the company's work (not generic flattery)
- One sentence about my relevant background
- One clear, low-pressure CTA
- Include a punchy subject line

JOBS:
{job_list}

Return ONLY a JSON array, one entry per job in the same order:
[
  {{"company": "...", "subject": "...", "body": "..."}},
  ...
]"""
    try:
        raw = claude_chat(prompt, system=SYSTEM_OUTREACH)
        data = parse_json_response(raw)
        if isinstance(data, dict):
            for key in ("emails", "results", "drafts"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError("Expected JSON array")
        # Align by position; fall back gracefully for missing entries
        results = []
        for i, job in enumerate(jobs):
            entry = data[i] if i < len(data) else {}
            results.append({
                "company": job["company"],
                "subject": entry.get("subject") or f"Interest in {job['title']} at {job['company']}",
                "body":    entry.get("body") or "",
            })
        return results
    except Exception:
        # Full fallback — individual calls so nothing is silently dropped
        log("  ⚠ Batch email draft failed — falling back to per-job calls")
        return [_draft_cold_email_single(job, bio) for job in jobs]


def _draft_cold_email_single(job: dict, bio: str, hm_name: str = "", hm_context: str = "") -> dict:
    """Single-job fallback, used when batch parse fails."""
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
        clean = raw.strip().strip("```json").strip("```").strip()
        return {"company": job["company"], **json.loads(clean)}
    except Exception:
        return {"company": job["company"], "subject": f"Interest in {job['title']} at {job['company']}", "body": raw}


# ── Save outreach draft ───────────────────────────────────────

def save_draft(content: str, job: dict, kind: str) -> str:
    path = Path(OUTREACH_DIR)
    path.mkdir(parents=True, exist_ok=True)
    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").strip().replace(" ", "_")
    filename = f"{today()}_{kind}_{safe(job['company'])}_{safe(job['title'])}.txt"
    (path / filename).write_text(content)
    return str(path / filename)


# ── Main pipeline ─────────────────────────────────────────────

def run(target_company: str = None, contact: str = None, contact_role: str = "", no_confirm: bool = False):
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

    if contact:
        # Warm referral — per-contact by nature, keep individual calls
        for job in jobs:
            log(f"\n→ {job['company']} — {job['title']}")
            draft = draft_warm_referral(job, contact, contact_role, YOUR_BIO)
            file_path = save_draft(
                f"WARM REFERRAL — {job['company']} — {job['title']}\n"
                f"Send to: {contact}\n\n{draft}",
                job, "warm_referral"
            )
            log(f"  ✓ Warm referral drafted → {file_path}")
            if no_confirm:
                log("  → Skipping confirm (non-interactive mode). Mark as 'Outreach Sent' manually.")
            else:
                confirm = input(f"\n  Mark '{job['company']}' as 'Outreach Sent'? (y/n): ").strip().lower()
                if confirm == "y":
                    db_update_status(job["page_id"], "Outreach Sent")
                    log("  ✓ Status updated → Outreach Sent")
    else:
        # Cold emails — draft all in a single batched API call
        log(f"  Drafting {len(jobs)} cold email(s) in one batch call…")
        emails = draft_cold_emails_batch(jobs, YOUR_BIO)
        email_by_company = {e["company"]: e for e in emails}

        for job in jobs:
            log(f"\n→ {job['company']} — {job['title']}")
            email = email_by_company.get(job["company"]) or {
                "subject": f"Interest in {job['title']} at {job['company']}", "body": ""
            }
            file_path = save_draft(
                f"COLD EMAIL — {job['company']} — {job['title']}\n"
                f"Subject: {email['subject']}\n\n{email['body']}",
                job, "cold_email"
            )
            log(f"  ✓ Cold email drafted → {file_path}")
            if no_confirm:
                log("  → Skipping confirm (non-interactive mode). Mark as 'Outreach Sent' manually.")
            else:
                confirm = input(f"\n  Mark '{job['company']}' as 'Outreach Sent'? (y/n): ").strip().lower()
                if confirm == "y":
                    db_update_status(job["page_id"], "Outreach Sent")
                    log("  ✓ Status updated → Outreach Sent")

    log(f"\nAll drafts saved to ./{OUTREACH_DIR}/")
    log("Review, personalise, and send them yourself.")


# ── InMail drafts (LinkedIn Premium Career) ──────────────────
# Career plan: 5 InMail credits/month → reserve for ATS score >= INMAIL_ATS_THRESHOLD
# LinkedIn InMail limits: subject ≤ 200 chars, body ≤ 1900 chars.

SYSTEM_INMAIL = """You are an expert at writing LinkedIn InMail messages for senior software engineers.
InMail works best when it is short, genuine, and human — NOT a cover letter.
Never use filler openers like 'I hope this message finds you well'.
The subject must be under 200 characters. The body must be under 1900 characters."""

INMAIL_DIR = "output/outreach"


def draft_inmail_batch(jobs: list[dict], bio: str) -> list[dict]:
    """Draft LinkedIn InMail messages for all jobs in a single API call.

    Returns [{company, subject, body}, ...] in the same order.
    Subject ≤ 200 chars, body ≤ 1900 chars — validated and truncated if needed.
    """
    if not jobs:
        return []

    job_list = "\n\n".join(
        f"{i+1}. Company: {j['company']}\n   Role: {j['title']}\n   ATS: {j.get('ats_score', '?')}"
        for i, j in enumerate(jobs)
    )
    prompt = f"""Write a LinkedIn InMail for EACH job below. I am a senior software engineer.

Rules for every InMail:
- Subject: punchy, specific, ≤ 200 characters (e.g. "Engineer excited about [Company]'s approach to X")
- Body: 3–4 short sentences total, ≤ 1900 characters
  • Sentence 1: one specific thing I find genuinely interesting about their product/engineering work
  • Sentence 2: one concrete, relevant thing from my background (no generic "I have X years of experience")
  • Sentence 3: single low-friction ask ("Happy to share more — open to a quick chat?")
- Write like a real person, not a template. No bullet points in the body.

My background: {bio}

JOBS:
{job_list}

Return ONLY a JSON array, one entry per job in the same order:
[
  {{"company": "...", "subject": "...", "body": "..."}},
  ...
]"""
    try:
        raw  = claude_chat(prompt, system=SYSTEM_INMAIL)
        data = parse_json_response(raw)
        if isinstance(data, dict):
            for key in ("inmails", "results", "messages"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError("Expected JSON array")
        results = []
        for i, job in enumerate(jobs):
            entry   = data[i] if i < len(data) else {}
            subject = (entry.get("subject") or f"Engineer interested in {job['title']} at {job['company']}")[:200]
            body    = (entry.get("body") or "")[:1900]
            results.append({"company": job["company"], "subject": subject, "body": body})
        return results
    except Exception as exc:
        log(f"  ⚠ InMail batch draft failed ({exc}) — falling back to per-job calls")
        return [_draft_inmail_single(job, bio) for job in jobs]


def _draft_inmail_single(job: dict, bio: str) -> dict:
    prompt = f"""Write a LinkedIn InMail for this job:
Company: {job['company']}
Role: {job['title']}
My background: {bio}

Subject ≤ 200 chars. Body ≤ 1900 chars, 3 sentences: (1) something specific about their work,
(2) one concrete thing from my background, (3) low-friction ask.

Return JSON: {{"subject": "...", "body": "..."}}"""
    raw = claude_chat(prompt, system=SYSTEM_INMAIL)
    try:
        import json as _json
        clean = raw.strip().strip("```json").strip("```").strip()
        d = _json.loads(clean)
        return {
            "company": job["company"],
            "subject": (d.get("subject") or "")[:200],
            "body":    (d.get("body") or "")[:1900],
        }
    except Exception:
        return {
            "company": job["company"],
            "subject": f"Engineer interested in {job['title']} at {job['company']}"[:200],
            "body":    raw[:1900],
        }


def run_inmail(target_company: str = None, no_confirm: bool = False):
    """Draft InMail messages for top-scoring Resume Tailored jobs."""
    from config.settings import INMAIL_ATS_THRESHOLD
    jobs = db_get_ready_to_apply()

    if not jobs:
        log("No 'Resume Tailored' jobs found. Run stage2_tailor.py first.")
        return

    if target_company:
        jobs = [j for j in jobs if target_company.lower() in j["company"].lower()]

    # Filter to jobs at or above the InMail ATS threshold
    eligible = [j for j in jobs if (j.get("ats_score") or 0) >= INMAIL_ATS_THRESHOLD]
    if not eligible:
        log(
            f"No jobs meet the InMail ATS threshold ({INMAIL_ATS_THRESHOLD}). "
            f"Highest score in 'Resume Tailored': "
            f"{max((j.get('ats_score') or 0) for j in jobs) if jobs else 'n/a'}"
        )
        return

    log(
        f"Drafting InMail for {len(eligible)} job(s) "
        f"(ATS >= {INMAIL_ATS_THRESHOLD}, out of {len(jobs)} Resume Tailored)"
    )

    inmails     = draft_inmail_batch(eligible, YOUR_BIO)
    inmail_map  = {m["company"]: m for m in inmails}

    Path(INMAIL_DIR).mkdir(parents=True, exist_ok=True)
    for job in eligible:
        log(f"\n→ {job['company']} — {job['title']}  (ATS: {job.get('ats_score', '?')})")
        msg  = inmail_map.get(job["company"]) or _draft_inmail_single(job, YOUR_BIO)
        safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").strip().replace(" ", "_")
        fname = f"{today()}_inmail_{safe(job['company'])}_{safe(job['title'])}.txt"
        fpath = Path(INMAIL_DIR) / fname
        fpath.write_text(
            f"LINKEDIN INMAIL — {job['company']} — {job['title']}\n"
            f"ATS Score : {job.get('ats_score', '?')}\n"
            f"Applicants: {job.get('applicant_count', 'unknown')}\n"
            f"Salary    : {job.get('salary_range', 'unknown')}\n"
            f"\nSubject ({len(msg['subject'])} chars): {msg['subject']}\n"
            f"\n{msg['body']}\n"
            f"\n--- char counts: subject={len(msg['subject'])}/200  body={len(msg['body'])}/1900 ---\n",
            encoding="utf-8",
        )
        log(f"  ✓ InMail drafted → {fpath}")
        log(f"    Subject ({len(msg['subject'])} chars): {msg['subject']}")

        if not no_confirm:
            input(f"\n  Press Enter after sending the InMail for {job['company']} (or Ctrl+C to stop)...")
            db_update_status(job["page_id"], "Outreach Sent")
            log("  ✓ Status updated → Outreach Sent")
        else:
            log("  → Non-interactive mode. Mark as 'Outreach Sent' manually after sending.")

    log(f"\nAll InMail drafts saved to ./{INMAIL_DIR}/")
    log("Reminder: LinkedIn Career gives 5 InMail credits/month — use them on your top matches.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company",      type=str,            default=None, help="Filter to specific company")
    parser.add_argument("--contact",      type=str,            default=None, help="Name of referral contact")
    parser.add_argument("--contact-role", type=str,            default="",   help="Their role at the company")
    parser.add_argument("--inmail",       action="store_true",               help="Draft LinkedIn InMail (Premium Career) instead of email")
    parser.add_argument("--no-confirm",   action="store_true",               help="Skip interactive status-update prompts")
    args = parser.parse_args()

    if args.inmail:
        run_inmail(target_company=args.company, no_confirm=args.no_confirm)
    else:
        run(target_company=args.company, contact=args.contact,
            contact_role=args.contact_role, no_confirm=args.no_confirm)
