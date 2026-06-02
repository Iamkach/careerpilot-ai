#!/usr/bin/env python3
"""
stage2_tailor.py — AI resume tailoring per job
────────────────────────────────────────────────
What it does:
  1. Fetches all "Scraped" jobs from Notion tracker
  2. For each job, uses Claude to rewrite your resume targeting that JD
  3. Saves tailored resume as a .txt file in output/resumes/
  4. Updates Notion: Status → "Resume Tailored", Tailored Resume Link

Run:  python scripts/stage2_tailor.py
  or: python scripts/stage2_tailor.py --min-score 60   (only score ≥ 60)
"""

import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat, load_resume,
    db_update_status, db_get_jobs,
    log, today, ensure_dirs,
)

SYSTEM_PROMPT = """You are an expert resume writer and ATS optimization specialist.
Your task: rewrite a resume to match a job description without inventing experience.
Surface existing skills with the right keywords. Be truthful. Be concise."""


# ── Fetch "Scraped" jobs from Supabase ───────────────────────

def get_scraped_jobs(min_score: int = 0) -> list:
    return db_get_jobs(status="Scraped", min_score=min_score)


# ── Fetch job description from URL ───────────────────────────

def fetch_jd(url: str) -> str:
    """Use Claude to read the job description from the URL."""
    if not url:
        return ""
    prompt = f"Fetch this job posting URL and return only the full job description text, nothing else:\n{url}"
    try:
        return claude_chat(prompt)
    except Exception:
        return ""


# ── Tailor resume using Claude ───────────────────────────────

def tailor_resume(resume: str, jd: str, job: dict) -> str:
    prompt = f"""Here is my current resume:

<resume>
{resume}
</resume>

Here is the job description I am applying to:

<job_description>
Company: {job['company']}
Role: {job['title']}

{jd}
</job_description>

Please:
1. Identify the top ATS keywords in the JD missing from my resume
2. Rewrite my resume to naturally incorporate them — do NOT invent experience
3. Prioritise bullet points that directly match the JD's requirements
4. Keep the same overall structure and length

Return the full rewritten resume text only. No commentary."""
    return claude_chat(prompt, system=SYSTEM_PROMPT, max_tokens=4000)


# ── Save tailored resume to file ─────────────────────────────

def save_resume(content: str, job: dict) -> str:
    ensure_dirs()
    safe_company = "".join(c for c in job["company"] if c.isalnum() or c in " _-").strip()
    safe_role    = "".join(c for c in job["title"]   if c.isalnum() or c in " _-").strip()
    filename = f"{today()}_{safe_company}_{safe_role}.txt".replace(" ", "_")
    path = Path(RESUMES_DIR) / filename
    path.write_text(content)
    return str(path)


# ── Main pipeline ─────────────────────────────────────────────

def run(min_score: int = 0):
    resume = load_resume()
    jobs = get_scraped_jobs(min_score=min_score)

    if not jobs:
        log("No 'Scraped' jobs found in Notion. Run stage1_scrape.py first.")
        return

    log(f"Tailoring resumes for {len(jobs)} jobs (min ATS score: {min_score})")

    for job in jobs:
        log(f"\n→ {job['company']} — {job['title']} (ATS: {job['ats_score']})")

        # Fetch JD
        jd = fetch_jd(job["url"])
        if not jd:
            log("  ⚠ Could not fetch job description. Skipping.")
            continue

        # Tailor
        tailored = tailor_resume(resume, jd, job)

        # Save locally
        file_path = save_resume(tailored, job)
        log(f"  ✓ Saved: {file_path}")

        # Update Supabase + mirror to Notion
        db_update_status(job["page_id"], "Resume Tailored", {
            "tailored_resume_link": f"file://{Path(file_path).resolve()}",
            "date_applied": today(),
        })
        log(f"  ✓ Status updated → Resume Tailored")

    log(f"\nAll done. Resumes saved to ./{RESUMES_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=int, default=0,
                        help="Only tailor resumes for jobs with ATS score >= this value")
    args = parser.parse_args()
    run(min_score=args.min_score)
