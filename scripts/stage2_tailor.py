#!/usr/bin/env python3
"""
stage2_tailor.py — AI resume tailoring per job
────────────────────────────────────────────────
What it does:
  1. Fetches all "Reviewed" jobs from Notion (jobs marked for application)
  2. Extracts text from config/Achyuth_Resume.docx as the base resume content
  3. For each job, asks Claude for targeted ATS keyword edits ({old, new} pairs)
  4. Copies Achyuth_Resume.docx, applies edits in-place → output/resumes/*.docx
     (preserves all original formatting; also writes a .txt mirror for quick review)
  5. Updates Notion: Status → "Resume Tailored", Tailored Resume Link

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
    log, today, ensure_dirs, ROOT, matches_company_list,
)
from scripts.render_docx import extract_docx_text, apply_docx_edits
from scripts.stage1_scrape import score_jobs_batch

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


# ── Fetch "Reviewed" jobs from Notion ─────────────────────────

def get_reviewed_jobs(min_score: int = 0) -> list:
    return db_get_jobs(status="Reviewed", min_score=min_score)


# ── Sponsorship gate ──────────────────────────────────────────

def _sponsorship_gate(jobs: list[dict]) -> list[dict]:
    """Hold back jobs at RESTRICTED_SPONSORSHIP_COMPANIES (companies known to sponsor only
    existing employees, not new hires) instead of tailoring a resume for them. A held job is
    moved to Notion Status='Human Review' with a guidance note. It's released once the user
    personally confirms sponsorship, adds SPONSORSHIP_CONFIRMED_MARKER to that job's Notion
    Notes, and moves Status back to 'Reviewed' by hand — without the marker check, a job
    moved back to 'Reviewed' would just get re-gated into 'Human Review' forever."""
    cleared = []
    for job in jobs:
        if not matches_company_list(job["company"], RESTRICTED_SPONSORSHIP_COMPANIES):
            cleared.append(job)
            continue
        notes = job.get("notes") or ""
        if SPONSORSHIP_CONFIRMED_MARKER.lower() in notes.lower():
            cleared.append(job)
            continue
        log(f"  ⚠ Holding back {job['company']} — known to sponsor existing employees only, not new hires.")
        log(f"    Moved to 'Human Review'. Confirm sponsorship for a new hire, add "
            f"\"{SPONSORSHIP_CONFIRMED_MARKER}\" to this job's Notion Notes, then set Status "
            f"back to 'Reviewed' to release it for tailoring.")
        guidance = (
            f"⚠ {job['company']} is known to sponsor only existing employees, not new hires. "
            f"Confirm sponsorship eligibility for a new hire, then add "
            f"\"{SPONSORSHIP_CONFIRMED_MARKER}\" here and move Status back to 'Reviewed' to "
            f"release it for tailoring."
        )
        db_update_status(job["page_id"], "Human Review", {
            "notes": f"{notes}\n{guidance}" if notes else guidance,
        })
    return cleared


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

def _tailor_resume_single(resume_text: str, jd: str, job: dict) -> tuple[list, list]:
    """Return a list of {old, new} text edits to apply to the base resume .docx.

    The resume_text is extracted verbatim from Achyuth_Resume.docx so Claude
    can quote exact strings for the "old" fields.
    """
    resume_block = {
        "type": "text",
        "text": f"Here is my current resume:\n\n<resume>\n{resume_text}\n</resume>",
        "cache_control": {"type": "ephemeral"},
    }
    hint_kws = job.get("missing_keywords") or []
    hint_line = (
        f"\nStage 1 flagged these as likely gaps (verify against the JD below before using — "
        f"not a checklist, and find additional ones it may have missed): {', '.join(hint_kws)}\n"
        if hint_kws else ""
    )
    jd_block = {
        "type": "text",
        "text": f"""Target job:

<job_description>
Company: {job['company']}
Role: {job['title']}
{hint_line}
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


def tailor_resumes_batch(
    resume_text: str,
    jobs_and_jds: list[tuple[dict, str]],
) -> dict[str, tuple[list, list]]:
    """One AI call for all jobs. Returns {page_id: (edits, keywords)}.
    Missing entries mean parse failed — caller falls back to _tailor_resume_single().
    """
    if not jobs_and_jds:
        return {}

    resume_block = {
        "type": "text",
        "text": f"RESUME (verbatim source for all 'old' fields):\n\n<resume>\n{resume_text}\n</resume>",
        "cache_control": {"type": "ephemeral"},
    }

    def _hint_line(job: dict) -> str:
        kws = job.get("missing_keywords") or []
        if not kws:
            return ""
        return f"\n   Stage 1 flagged these as likely gaps (verify against the JD below before using — not a checklist): {', '.join(kws)}"

    job_entries = "\n\n".join(
        f"{i+1}. Company: {job['company']}\n"
        f"   Role: {job['title']}"
        f"{_hint_line(job)}\n"
        f"   <job_description>\n{jd[:2000]}\n   </job_description>"
        for i, (job, jd) in enumerate(jobs_and_jds)
    )

    prompt_block = {
        "type": "text",
        "text": f"""For EACH numbered job, produce one JSON entry with targeted resume edits.

Where a job lists "Stage 1 flagged these as likely gaps," treat it as a starting point only —
confirm each one is actually supported by the full job description before injecting it, and feel
free to find additional missing keywords the flagged list didn't catch.

Edit priority (highest impact first):
  1. TITLE LINE: Replace header title with exact role title from JD if different. REQUIRED unless identical.
  2. PROFESSIONAL SUMMARY: Front-load 3-5 missing JD keywords, keep all real metrics and facts.
  3. TECHNICAL SKILLS: Append missing keywords to the most relevant existing skill category only.
  4. TOP BULLETS (2-4 max): Inject 1-2 missing keywords per bullet into the highest-signal bullets.

Hard constraints:
  - "old" must be EXACT verbatim text from the resume above — character for character
  - Never invent tools, technologies, companies, metrics, or dates
  - Do not change bullet meaning — only add missing terminology where it genuinely fits
  - Prefer depth over breadth: 5 strong edits beats 15 shallow ones

JOBS:
{job_entries}

Return ONLY a JSON array (no markdown fences, no commentary):
[
  {{
    "job_index": 1,
    "company": "...",
    "keywords_injected": ["k1", "k2"],
    "edits": [
      {{"old": "exact verbatim text", "new": "updated text", "reason": "one-line rationale"}}
    ]
  }}
]""",
    }

    max_tok = min(4000 + 1500 * len(jobs_and_jds), 16000)
    raw = ai_chat_blocks([resume_block, prompt_block], system=SYSTEM_PROMPT,
                         max_tokens=max_tok, quality=True)

    try:
        data = parse_json_response(raw)
        if isinstance(data, dict):
            for key in ("results", "jobs", "edits"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array, got {type(data)}")
    except Exception as exc:
        log(f"  ⚠ Batch parse failed ({exc}) — will fall back per-job")
        return {}

    by_index: dict[int, dict] = {}
    by_company: dict[str, dict] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("job_index")
        if idx is not None:
            by_index[int(idx)] = entry
        company = (entry.get("company") or "").lower()
        if company:
            by_company[company] = entry

    results: dict[str, tuple[list, list]] = {}
    for i, (job, _) in enumerate(jobs_and_jds):
        pid = job.get("page_id") or job.get("id")
        entry = by_index.get(i + 1) or by_company.get(job["company"].lower())
        if entry and isinstance(entry.get("edits"), list):
            results[pid] = (entry["edits"], entry.get("keywords_injected", []))
    return results


# ── Save tailored resume to file ─────────────────────────────

def _resume_title_line(resume_text: str) -> str:
    """The resume's header role line — 3rd non-empty line (name, contact, title)."""
    lines = [l for l in resume_text.split("\n") if l.strip()]
    return lines[2] if len(lines) > 2 else ""


def save_resume(edits: list, job: dict, resume_text: str) -> str:
    """Apply edits to the base .docx and save to output/resumes/.

    Copies Achyuth_Resume.docx, patches each edited paragraph in-place, and
    writes a plain-text mirror alongside the .docx for quick review.
    Returns the path to the saved .docx.

    The header title line is forced to match job["title"] deterministically
    rather than relying on the AI to have proposed a matching edit — the AI's
    title-line edit is easy to drop (token budget in large batches, exact-match
    quoting) since it's the only purely mechanical edit in the list.
    """
    ensure_dirs()
    safe_company = "".join(c for c in job["company"] if c.isalnum() or c in " _-").strip()
    safe_role    = "".join(c for c in job["title"]   if c.isalnum() or c in " _-").strip()
    stem = f"{today()}_{safe_company}_{safe_role}".replace(" ", "_")
    docx_path = str(Path(RESUMES_DIR) / f"{stem}.docx")
    base = str(ROOT / RESUME_TEMPLATE_PATH)

    title_line = _resume_title_line(resume_text)
    job_title = (job.get("title") or "").strip()
    final_edits = list(edits)
    if title_line and job_title and title_line.strip().lower() != job_title.lower():
        final_edits = [e for e in final_edits if (e.get("old") or "").strip() != title_line]
        final_edits.insert(0, {"old": title_line, "new": job_title})

    docx_path, unmatched = apply_docx_edits(base, final_edits, docx_path, job=job)
    if unmatched:
        for e in unmatched:
            log(f"  ⚠ Edit did not match any paragraph, skipped: {e.get('old', '')[:80]!r}")

    # Plain-text mirror: re-extract from the saved docx for quick review.
    txt_path = docx_path.replace(".docx", ".txt")
    Path(txt_path).write_text(extract_docx_text(docx_path), encoding="utf-8")

    return docx_path


# ── Post-tailor verification ──────────────────────────────────

def verify_tailored_score(tailored_resume_text: str, jd: str, job: dict) -> dict:
    """Re-score the tailored resume against the same JD, reusing stage 1's exact scoring
    contract (score_jobs_batch) so "score" means the same thing before and after tailoring.
    Returns {url, score, scored, missing_keywords, sponsorship, company_type} — score/scored
    follow the same "never fabricate a score" contract as stage 1."""
    results = score_jobs_batch(
        [{"url": job["url"], "title": job["title"], "company": job["company"], "description": jd}],
        tailored_resume_text,
    )
    return results[0] if results else {"url": job["url"], "score": None, "scored": False}


# ── Main pipeline ─────────────────────────────────────────────

def run(min_score: int = 0):
    resume_text = load_base_resume_text()
    jobs = get_reviewed_jobs(min_score=min_score)
    jobs = _sponsorship_gate(jobs)

    if not jobs:
        log("No 'Reviewed' jobs found (or all held pending sponsorship confirmation — see 'Human Review'). "
            "Mark jobs as Reviewed in Notion, then run: python run.py --evaluate")
        return

    log(f"Tailoring resumes for {len(jobs)} jobs (min ATS score: {min_score})")

    # Phase 1: Fetch all JDs (no AI)
    jobs_and_jds: list[tuple[dict, str]] = []
    for job in jobs:
        log(f"  Fetching JD: {job['company']} — {job['title']}")
        jd = db_get_job_description(job.get("id") or job.get("page_id"))
        if not jd:
            log("  ↳ No cached JD — fetching from URL…")
            jd = fetch_jd(job["url"])
        if not jd:
            log(f"  ⚠ Could not fetch JD — skipping {job['company']}.")
            continue
        jobs_and_jds.append((job, jd))

    if not jobs_and_jds:
        log("No jobs with accessible JDs. Nothing to tailor.")
        return

    # Phase 2: ONE batch AI call for all jobs
    log(f"\nBatch tailoring {len(jobs_and_jds)} job(s) in 1 AI call…")
    batch_results = tailor_resumes_batch(resume_text, jobs_and_jds)

    missing = [(j, d) for j, d in jobs_and_jds
               if (j.get("page_id") or j.get("id")) not in batch_results]
    if missing:
        log(f"  ↳ Batch missed {len(missing)} job(s) — falling back to per-job calls")
        for job, jd in missing:
            log(f"    → {job['company']} — single-job fallback")
            edits, keywords = _tailor_resume_single(resume_text, jd, job)
            pid = job.get("page_id") or job.get("id")
            batch_results[pid] = (edits, keywords)

    # Phase 3: Apply edits + verify + update Notion
    for job, jd in jobs_and_jds:
        pid = job.get("page_id") or job.get("id")
        log(f"\n→ {job['company']} — {job['title']} (ATS: {job['ats_score']})")
        edits, keywords = batch_results.get(pid, ([], []))
        log(f"  ↳ {len(edits)} edit(s) suggested")
        if keywords:
            log(f"  ↳ Keywords injected: {', '.join(keywords)}")
        stage1_hints = job.get("missing_keywords") or []
        if stage1_hints:
            injected_lower = {k.lower() for k in keywords}
            dropped = [k for k in stage1_hints if k.lower() not in injected_lower]
            if dropped:
                log(f"  ↳ Stage 1 flagged but not injected: {', '.join(dropped)}")

        file_path = save_resume(edits, job, resume_text)
        log(f"  ✓ Saved: {file_path}")

        tailored_text = extract_docx_text(file_path)
        verify = verify_tailored_score(tailored_text, jd, job)
        before = job["ats_score"]
        if verify["scored"]:
            after = verify["score"]
            log(f"  ↳ ATS: {before} → {after}")
            if after < MIN_TAILORED_ATS_SCORE:
                log(f"  ⚠ Tailored resume for {job['company']} — {job['title']} scored {after}, "
                    f"below MIN_TAILORED_ATS_SCORE={MIN_TAILORED_ATS_SCORE} — worth a manual look.")
        else:
            log(f"  ⚠ Post-tailor verification scoring failed for {job['company']} — leaving as-is.")

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
