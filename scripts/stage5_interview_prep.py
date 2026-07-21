#!/usr/bin/env python3
"""
stage5_interview_prep.py — AI interview prep guide per company
───────────────────────────────────────────────────────────────
What it does:
  1. Takes a company name (looks up from Notion or you can pass JD directly)
  2. Uses Claude to generate a custom prep guide:
     - Behavioral + technical questions
     - Questions tailored to hiring manager's background
     - STAR answer frameworks for hardest questions
     - Smart questions to ask them
  3. Saves as a clean HTML file in output/prep_guides/
  4. Updates Notion Status → "Interview Scheduled"

Run:
  python scripts/stage5_interview_prep.py --company "Stripe" --role "PM, Payments"
  python scripts/stage5_interview_prep.py --company "Google" --jd-file path/to/jd.txt
  python scripts/stage5_interview_prep.py --company "Meta" --hm-linkedin "https://linkedin.com/in/..."
"""

import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat, load_resume, wrap_consecutive_li,
    db_update_status, db_get_job_by_company, db_get_job_description,
    log, today, ensure_dirs,
)

SYSTEM_PREP = """You are an expert interview coach with deep knowledge of tech industry
interviews, particularly for product management, engineering, and business roles.
Generate highly specific, tailored interview prep — not generic advice."""


# ── Fetch job details from Notion ────────────────────────────

def get_job_from_notion(company: str) -> dict | None:
    return db_get_job_by_company(company)


# ── Generate prep guide ───────────────────────────────────────

def generate_prep_guide(job: dict, jd: str, hm_linkedin: str, resume: str) -> str:
    hm_section = f"\nHiring manager LinkedIn: {hm_linkedin}" if hm_linkedin else ""
    prompt = f"""Generate a comprehensive interview prep guide for:

Company: {job['company']}
Role: {job.get('title', 'Unknown Role')}
My resume summary:
{resume[:2000]}

Job description:
{jd[:3000]}
{hm_section}

Please generate:

## 1. Company & role context (3–4 bullet points)
Key things to know about this company's culture, product, and what they value in this role.

## 2. Behavioral questions (5 questions)
Tailored to this company's known values. For each: the question + a STAR framework hint.

## 3. Technical / role-specific questions (5 questions)
Based on the JD requirements. For each: the question + what a strong answer covers.

## 4. Hiring manager-focused questions (3 questions)
Based on their background{' from LinkedIn' if hm_linkedin else ''}.
What are their likely priorities and pain points?

## 5. STAR answer frameworks (top 3 hardest questions)
Full suggested answer structure for the 3 most challenging questions above.

## 6. Questions to ask them (5 smart questions)
Questions that show strategic thinking and genuine curiosity — not generic ones.

## 7. Quick cheat sheet
3 bullet points: what to emphasize, what to avoid, one memorable hook.

Format cleanly with clear headers. Be specific — no generic advice."""
    return claude_chat(prompt, system=SYSTEM_PREP, max_tokens=6000, quality=True)


# ── Render HTML prep guide ────────────────────────────────────

def render_html(content: str, job: dict) -> str:
    import re
    # Convert markdown-ish to HTML
    html_body = content
    html_body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^\* (.+)$',  r'<li>\1</li>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^\- (.+)$',  r'<li>\1</li>', html_body, flags=re.MULTILINE)
    html_body = wrap_consecutive_li(html_body)
    html_body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_body)
    html_body = html_body.replace("\n\n", "</p><p>")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Interview Prep — {job['company']} — {job.get('title','')}</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.65; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #1a1a1a; padding-bottom: 10px; }}
  h2 {{ font-size: 17px; margin-top: 32px; color: #2c2c2c; border-left: 3px solid #0066cc; padding-left: 10px; }}
  h3 {{ font-size: 15px; color: #444; }}
  li {{ margin: 6px 0; }}
  p  {{ margin: 8px 0; }}
  .meta {{ font-size: 13px; color: #666; margin-bottom: 24px; }}
  .cheatsheet {{ background: #f0f7ff; border: 1px solid #cce0ff; border-radius: 8px; padding: 16px 20px; margin-top: 24px; }}
</style>
</head>
<body>
  <h1>Interview Prep — {job['company']}</h1>
  <p class="meta">Role: {job.get('title','—')} &nbsp;·&nbsp; Generated: {today()} &nbsp;·&nbsp; <a href="{job.get('url','#')}">Job posting</a></p>
  <p>{html_body}</p>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────

def run(company: str, role: str = "", jd_file: str = "", hm_linkedin: str = "", no_confirm: bool = False):
    resume = load_resume()
    ensure_dirs()

    # Get job from Notion
    job = get_job_from_notion(company) or {"company": company, "title": role, "url": "", "page_id": None}
    if role:
        job["title"] = role

    def _need_manual_jd() -> str:
        # In an unattended run there's no one to paste a JD into stdin — input() would just
        # hang until EOFError kills the process. Fail with a clear, actionable message
        # instead (same "don't block on input(), fail loudly" principle stage3_outreach's
        # no_confirm path already follows), rather than crashing with an opaque traceback.
        if no_confirm:
            raise RuntimeError(
                f"No JD available for {job['company']} — {job.get('title','')} (no cached JD, "
                "no URL to fetch, and --no-confirm disables the manual-paste prompt). "
                "Pass --jd-file pointing at a .txt file with the job description, or add the "
                "JD to this job's cached body in Notion, then retry."
            )
        return input("Paste the job description (press Enter twice when done):\n")

    # Get JD — prefer cached DB value to avoid an extra AI call
    if jd_file:
        jd = Path(jd_file).read_text()
    elif job.get("page_id"):
        jd = db_get_job_description(job["page_id"])
        if not jd and job.get("url"):
            log("No cached JD — fetching from URL (one-time AI call)…")
            jd = claude_chat(f"Fetch and return only the job description text from: {job['url']}")
        if not jd:
            jd = _need_manual_jd()
    elif job.get("url"):
        log("Fetching job description from URL...")
        jd = claude_chat(f"Fetch and return only the job description text from: {job['url']}")
    else:
        jd = _need_manual_jd()

    hm_li = hm_linkedin or job.get("hm_li", "")

    log(f"Generating prep guide for {job['company']} — {job.get('title','')}")
    guide_md = generate_prep_guide(job, jd, hm_li, resume)

    # Save HTML
    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").replace(" ", "_")
    filename = f"prep_{safe(job['company'])}_{safe(job.get('title',''))}_{today()}.html"
    out_path = Path(PREP_GUIDES_DIR) / filename
    out_path.write_text(render_html(guide_md, job))
    log(f"✓ Prep guide saved: {out_path}")

    # Update status
    if job.get("page_id"):
        db_update_status(job["page_id"], "Interview Scheduled")
        log("✓ Status updated → Interview Scheduled")

    print(f"\nOpen your prep guide:\n  {out_path.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company",      required=True,        help="Company name")
    parser.add_argument("--role",         default="",           help="Role title")
    parser.add_argument("--jd-file",      default="",           help="Path to .txt file with job description")
    parser.add_argument("--hm-linkedin",  default="",           help="Hiring manager LinkedIn URL")
    parser.add_argument("--no-confirm",   action="store_true",  dest="no_confirm",
                         help="Fail with a clear error instead of prompting for a manual JD paste")
    args = parser.parse_args()
    run(company=args.company, role=args.role, jd_file=args.jd_file, hm_linkedin=args.hm_linkedin,
        no_confirm=args.no_confirm)
