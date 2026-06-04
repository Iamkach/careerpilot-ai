#!/usr/bin/env python3
"""
stage2_tailor.py — AI resume tailoring per job
────────────────────────────────────────────────
What it does:
  1. Fetches all "Scraped" jobs from Notion tracker
  2. For each job, uses Claude to rewrite your resume targeting that JD,
     returning structured JSON (name, summary, skills, experience, education)
  3. Renders that JSON into config/resume_template.docx → output/resumes/*.docx
     (plus a .txt mirror for quick review)
  4. Updates Notion: Status → "Resume Tailored", Tailored Resume Link

Run:  python scripts/stage2_tailor.py
  or: python scripts/stage2_tailor.py --min-score 60   (only score ≥ 60)
"""

import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat, ai_chat_blocks, load_resume, parse_json_response,
    db_update_status, db_get_jobs, db_get_job_description,
    log, today, ensure_dirs, ROOT,
)
from scripts.render_docx import render_resume_docx, resume_data_to_text

SYSTEM_PROMPT = """You are an expert resume writer and ATS optimization specialist.
Your task: rewrite a resume to match a job description without inventing experience.
Surface existing skills with the right keywords. Be truthful. Be concise.
You always respond with valid JSON only — no prose, no markdown fences."""


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

def tailor_resume(resume: str, jd: str, job: dict) -> dict:
    """Return tailored resume content as a structured dict (template-ready)."""
    # Resume block is cached — same across every call in this stage run.
    resume_block = {
        "type": "text",
        "text": f"Here is my current resume:\n\n<resume>\n{resume}\n</resume>",
        "cache_control": {"type": "ephemeral"},
    }
    jd_block = {
        "type": "text",
        "text": f"""\nHere is the job description I am applying to:

<job_description>
Company: {job['company']}
Role: {job['title']}

{jd}
</job_description>

Tailor my resume to this job:
1. Identify the top ATS keywords in the JD missing from my resume
2. Naturally incorporate them — do NOT invent experience, employers, dates, or degrees
3. Prioritise bullets that directly match the JD's requirements
4. Keep my real name, contact details, employers, titles, dates, and education exactly as in my resume

Return ONLY a JSON object with this exact shape (no markdown, no commentary):
{{
  "name": "Full Name",
  "contact": "email | linkedin | location",
  "summary": "2-3 sentence professional summary tailored to this role",
  "skills": ["skill 1", "skill 2", "..."],
  "experience": [
    {{
      "company": "Company Name",
      "title": "Job Title",
      "dates": "Jan 2022 – Present",
      "bullets": ["achievement bullet 1", "achievement bullet 2"]
    }}
  ],
  "education": [
    {{"institution": "University", "degree": "Degree", "year": "Year"}}
  ]
}}""",
    }
    raw = ai_chat_blocks([resume_block, jd_block], system=SYSTEM_PROMPT, max_tokens=4000, quality=True)
    data = parse_json_response(raw)
    # Authoritative identity from config — never let the model alter the name.
    if YOUR_NAME:
        data["name"] = YOUR_NAME
    return data


# ── Save tailored resume to file ─────────────────────────────

def save_resume(data: dict, job: dict) -> str:
    """Render the tailored resume to .docx (via template) and a .txt mirror.

    Returns the path to the .docx (falls back to .txt if the template is
    missing so the stage still produces output).
    """
    ensure_dirs()
    safe_company = "".join(c for c in job["company"] if c.isalnum() or c in " _-").strip()
    safe_role    = "".join(c for c in job["title"]   if c.isalnum() or c in " _-").strip()
    stem = f"{today()}_{safe_company}_{safe_role}".replace(" ", "_")
    base = Path(RESUMES_DIR) / stem

    # Always write a plain-text mirror for quick review.
    txt_path = base.with_suffix(".txt")
    txt_path.write_text(resume_data_to_text(data), encoding="utf-8")

    # Render the formatted .docx from the user's template.
    docx_path = base.with_suffix(".docx")
    template = str(ROOT / RESUME_TEMPLATE_PATH)
    try:
        render_resume_docx(data, template, str(docx_path))
        return str(docx_path)
    except FileNotFoundError as e:
        log(f"  ⚠ {e}")
        log(f"  ↳ Saved .txt only: {txt_path}")
        return str(txt_path)


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

        # Use cached JD from Supabase if available; fall back to fetching via AI
        jd = job.get("job_description") or db_get_job_description(job["page_id"])
        if not jd:
            log("  ↳ No cached JD — fetching from URL (one-time AI call)…")
            jd = fetch_jd(job["url"])
        if not jd:
            log("  ⚠ Could not fetch job description. Skipping.")
            continue

        # Tailor
        tailored = tailor_resume(resume, jd, job)

        # Save locally
        file_path = save_resume(tailored, job)
        log(f"  ✓ Saved: {file_path}")

        # Update Supabase + mirror to Notion.
        # NOTE: do NOT set date_applied here — tailoring is not applying.
        # The digest (db_get_ready_to_apply) shows 'Resume Tailored' jobs where
        # date_applied IS NULL, so setting it here would hide every job.
        db_update_status(job["page_id"], "Resume Tailored", {
            "tailored_resume_link": f"file://{Path(file_path).resolve()}",
        })
        log(f"  ✓ Status updated → Resume Tailored")

    log(f"\nAll done. Resumes saved to ./{RESUMES_DIR}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=int, default=0,
                        help="Only tailor resumes for jobs with ATS score >= this value")
    args = parser.parse_args()
    run(min_score=args.min_score)
