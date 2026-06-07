#!/usr/bin/env python3
"""
stage2_tailor.py — AI resume tailoring per job
────────────────────────────────────────────────
What it does:
  1. Fetches all "Reviewed" jobs from Supabase (jobs marked for application)
  2. Extracts text from config/Achyuth_Resume.docx as the base resume content
  3. For each job, asks Claude for targeted ATS keyword edits ({old, new} pairs)
  4. Copies Achyuth_Resume.docx, applies edits in-place → output/resumes/*.docx
     (preserves all original formatting; also writes a .txt mirror for quick review)
  5. Updates Supabase: Status → "Resume Tailored", Tailored Resume Link

Run:  python run.py --evaluate
  or: python run.py --stage 2 --min-score 60   (only score ≥ 60 from Reviewed status)
"""

import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    ai_chat_blocks, parse_json_response,
    db_update_status, db_get_jobs, db_get_job_description,
    log, today, ensure_dirs, ROOT,
)
from scripts.render_docx import extract_docx_text, apply_docx_edits

SYSTEM_PROMPT = """You are an expert resume writer and ATS optimization specialist.
Your task: suggest targeted edits to an existing resume to incorporate missing ATS keywords.
The "old" text must be verbatim from the resume — never invent experience, titles, or dates.
You always respond with valid JSON only — no prose, no markdown fences."""


# ── Load base resume text from the .docx ──────────────────────

def load_base_resume_text() -> str:
    """Extract plain text from the base resume .docx for use in Claude prompts."""
    docx_path = str(ROOT / RESUME_TEMPLATE_PATH)
    try:
        return extract_docx_text(docx_path)
    except FileNotFoundError:
        # Fall back to resume.txt if the docx isn't present yet
        from scripts.utils import load_resume
        return load_resume()


# ── Fetch "Reviewed" jobs from Supabase ───────────────────────

def get_reviewed_jobs(min_score: int = 0) -> list:
    return db_get_jobs(status="Reviewed", min_score=min_score)


# ── Fetch job description from URL ───────────────────────────

def fetch_jd(url: str) -> str:
    """Fetch job description text from URL via HTTP."""
    if not url:
        return ""
    import requests, re
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return ""
        # Strip HTML tags and collapse whitespace
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:8000]
    except Exception:
        return ""


# ── Tailor resume using Claude ───────────────────────────────

def tailor_resume(resume_text: str, jd: str, job: dict) -> list:
    """Return a list of {old, new} text edits to apply to the base resume .docx.

    The resume_text is extracted verbatim from Achyuth_Resume.docx so Claude
    can quote exact strings for the "old" fields.
    """
    resume_block = {
        "type": "text",
        "text": f"Here is my current resume:\n\n<resume>\n{resume_text}\n</resume>",
        "cache_control": {"type": "ephemeral"},
    }
    jd_block = {
        "type": "text",
        "text": f"""Here is the job description I am applying to:

<job_description>
Company: {job['company']}
Role: {job['title']}

{jd}
</job_description>

Identify the minimal, highest-impact changes to incorporate missing ATS keywords into my resume.

Rules:
1. The "old" field must be the EXACT verbatim text from my resume — copy it character-for-character
2. Do NOT invent experience, employers, job titles, dates, degrees, or metrics
3. Only update existing bullet points / the summary to naturally include missing keywords
4. Keep my name, contact details, company names, titles, and dates unchanged
5. Prefer updating the summary and a few high-signal bullets over many shallow changes

Return ONLY a JSON object (no markdown, no commentary):
{{
  "edits": [
    {{"old": "exact existing text from resume", "new": "updated text with ATS keywords"}}
  ]
}}""",
    }
    raw = ai_chat_blocks([resume_block, jd_block], system=SYSTEM_PROMPT, max_tokens=4000, quality=True)
    data = parse_json_response(raw)
    if isinstance(data, dict):
        return data.get("edits", [])
    return []


# ── Save tailored resume to file ─────────────────────────────

def save_resume(edits: list, job: dict) -> str:
    """Apply edits to the base .docx and save to output/resumes/.

    Copies Achyuth_Resume.docx, patches each edited paragraph in-place, and
    writes a plain-text mirror alongside the .docx for quick review.
    Returns the path to the saved .docx.
    """
    ensure_dirs()
    safe_company = "".join(c for c in job["company"] if c.isalnum() or c in " _-").strip()
    safe_role    = "".join(c for c in job["title"]   if c.isalnum() or c in " _-").strip()
    stem = f"{today()}_{safe_company}_{safe_role}".replace(" ", "_")
    docx_path = str(Path(RESUMES_DIR) / f"{stem}.docx")
    base = str(ROOT / RESUME_TEMPLATE_PATH)

    apply_docx_edits(base, edits, docx_path)

    # Plain-text mirror: re-extract from the saved docx for quick review.
    txt_path = docx_path.replace(".docx", ".txt")
    Path(txt_path).write_text(extract_docx_text(docx_path), encoding="utf-8")

    return docx_path


# ── Main pipeline ─────────────────────────────────────────────

def run(min_score: int = 0):
    resume_text = load_base_resume_text()
    jobs = get_reviewed_jobs(min_score=min_score)

    if not jobs:
        log("No 'Reviewed' jobs found. Mark jobs as Reviewed in Notion, then run: python run.py --evaluate")
        return

    log(f"Tailoring resumes for {len(jobs)} jobs (min ATS score: {min_score})")

    for job in jobs:
        log(f"\n→ {job['company']} — {job['title']} (ATS: {job['ats_score']})")

        # Use cached JD from Supabase; fall back to URL fetch
        jd = db_get_job_description(job["id"])
        if not jd:
            log("  ↳ No cached JD — fetching from URL…")
            jd = fetch_jd(job["url"])
        if not jd:
            log("  ⚠ Could not fetch job description. Skipping.")
            continue

        # Ask Claude for targeted keyword edits
        edits = tailor_resume(resume_text, jd, job)
        log(f"  ↳ {len(edits)} edit(s) suggested")

        # Apply edits to a copy of Achyuth_Resume.docx
        file_path = save_resume(edits, job)
        log(f"  ✓ Saved: {file_path}")

        # Update Supabase + mirror to Notion.
        # NOTE: do NOT set date_applied here — tailoring is not applying.
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
