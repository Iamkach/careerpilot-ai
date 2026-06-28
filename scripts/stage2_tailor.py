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

SYSTEM_PROMPT = """You are a senior technical recruiter and ATS optimization expert.
Your task: maximize the ATS match score between a candidate's resume and a target job description.
Rules you must never break:
  - The "old" field must be EXACT verbatim text copied from the resume — character for character
  - Never invent experience, employers, degrees, dates, or metrics
  - Never change the candidate's name, contact info, company names, or employment dates
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

def tailor_resume(resume_text: str, jd: str, job: dict) -> tuple[list, list]:
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
        "text": f"""Target job:

<job_description>
Company: {job['company']}
Role: {job['title']}

{jd}
</job_description>

STEP 1 — Silently extract from the JD:
  a) The EXACT job title as written in the JD (e.g. "Staff Software Engineer", "Senior Backend Engineer")
  b) Must-have tech keywords present in the JD but MISSING from my resume (focus on: languages, frameworks, tools, patterns, methodologies, cloud services, ML/AI terms)
  c) The top 3 high-signal bullets in my resume that are closest to the JD's core requirements

STEP 2 — Produce targeted edits using only what you extracted:

Edit priority order (highest impact first):
  1. TITLE LINE: Replace the header title "Senior Software Engineer" with the exact role title from the JD if it differs. This edit is REQUIRED unless the title is identical.
  2. PROFESSIONAL SUMMARY: Rewrite to front-load the top 3–5 missing keywords from the JD while keeping all real metrics and facts from the original. Match the seniority and domain framing of the JD.
  3. TECHNICAL SKILLS: Add missing JD keywords into the most relevant skill category. Do not add a category; append to existing lines only.
  4. TOP BULLETS (2–4 max): Inject 1–2 missing keywords per bullet into the highest-signal bullets. Rewrite minimally — change only what's needed to include the keyword naturally.

Hard constraints:
  - "old" must be copied verbatim from my resume, character-for-character including punctuation
  - Do not invent tools, technologies, companies, metrics, or dates
  - Do not change bullet meaning — only add missing terminology where it genuinely fits
  - If a keyword cannot be added truthfully to any existing content, skip it
  - Prefer depth over breadth: 5 strong edits beats 15 shallow ones

Return ONLY this JSON (no markdown fences, no commentary):
{{
  "keywords_injected": ["keyword1", "keyword2"],
  "edits": [
    {{"old": "exact verbatim text from resume", "new": "updated text with ATS keywords", "reason": "one-line rationale"}}
  ]
}}""",
    }
    raw = ai_chat_blocks([resume_block, jd_block], system=SYSTEM_PROMPT, max_tokens=4000, quality=True)
    data = parse_json_response(raw)
    if isinstance(data, dict):
        keywords = data.get("keywords_injected", [])
        edits = data.get("edits", [])
        return edits, keywords
    return [], []


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
        edits, keywords = tailor_resume(resume_text, jd, job)
        log(f"  ↳ {len(edits)} edit(s) suggested")
        if keywords:
            log(f"  ↳ Keywords injected: {', '.join(keywords)}")

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
