#!/usr/bin/env python3
"""
stage1_scrape.py — Scrape fresh LinkedIn jobs & log to Notion
─────────────────────────────────────────────────────────────
What it does:
  1. Runs Apify LinkedIn scraper for each target role
  2. Filters to jobs posted in last 24–48h
  3. Scores each job against your resume using Claude
  4. Skips duplicates already in Notion
  5. Adds new jobs to Notion tracker with Status = "Scraped"

Run:  python scripts/stage1_scrape.py
"""

import sys, time, re, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import claude_chat, parse_json_response, load_resume, db_add_job, db_find_job_by_url, log, today

# Apify REST API addresses actors as username~actorname (NOT username/actorname,
# which 404s). curious_coder~linkedin-jobs-scraper is the LinkedIn jobs scraper.
APIFY_ACTOR = "curious_coder~linkedin-jobs-scraper"
APIFY_BASE  = "https://api.apify.com/v2"


# ── 1. Scrape LinkedIn via Apify ─────────────────────────────

def scrape_jobs(role: str, city: str, max_results: int = 10) -> list[dict]:
    log(f"Scraping LinkedIn for: '{role}' in '{city}'")
    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs"
    search_url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={requests.utils.quote(role)}"
        f"&location={requests.utils.quote(city)}&f_TPR=r86400"
    )
    payload = {
        # Actor schema: `urls` (array of LinkedIn search/job URLs) + `count` (min 10).
        "urls": [search_url],
        "count": max(max_results, 10),
        "scrapeCompany": False,
    }
    r = requests.post(run_url, json=payload, params={"token": APIFY_API_TOKEN})
    r.raise_for_status()
    run_id = r.json()["data"]["id"]

    # Poll until finished
    for _ in range(30):
        time.sleep(10)
        status_r = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": APIFY_API_TOKEN})
        status = status_r.json()["data"]["status"]
        log(f"  Apify run status: {status}")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Apify run {status}")

    dataset_id = status_r.json()["data"]["defaultDatasetId"]
    items_r = requests.get(f"{APIFY_BASE}/datasets/{dataset_id}/items", params={"token": APIFY_API_TOKEN})
    return items_r.json()


# ── US location filter ───────────────────────────────────────

_US_LOCATION_RE = re.compile(
    r'\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|'
    r'MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|'
    r'UT|VT|VA|WA|WV|WI|WY|DC)\b'
    r'|United States|Remote',
    re.IGNORECASE,
)


def is_us_location(location: str) -> bool:
    """True if location is blank (unknown) or clearly in the US."""
    if not location:
        return True  # keep unknowns — LinkedIn often omits location for remote roles
    return bool(_US_LOCATION_RE.search(location))


# ── Company denylist ─────────────────────────────────────────

def is_skipped_company(company: str) -> bool:
    """True if the company matches any entry in SKIP_COMPANIES (case-insensitive
    substring), i.e. an IT-services / consulting / staffing firm to exclude."""
    name = (company or "").lower()
    return any(bad.lower() in name for bad in SKIP_COMPANIES)


# ── Deterministic no-sponsorship detection (full JD text) ────
# Scans the ENTIRE job description, not a truncated slice — the visa/EEO
# boilerplate (e.g. Capital One's "will not sponsor …") usually sits at the end
# of the posting, past where the LLM scoring prompt truncates the text.
_NO_SPONSORSHIP_PATTERNS = [
    r"will not sponsor",
    r"\bnot sponsor\b",
    r"do(?:es)? not (?:provide|offer|support).{0,40}sponsor",
    r"(?:un)?able to sponsor",                       # "not able to sponsor" / "unable to sponsor"
    r"not (?:be )?(?:able|eligible|in a position) to sponsor",
    r"no(?:t)?\s+(?:visa\s+)?sponsorship",           # "no sponsorship", "not ... sponsorship"
    r"sponsorship (?:is )?not (?:available|offered|provided|possible)",
    r"without (?:the need for )?(?:visa |employer )?sponsorship",
    r"authoriz(?:ed|ation) to work .{0,50}without (?:visa )?sponsorship",
    r"do(?:es)? not (?:provide|offer).{0,40}immigration",
    r"\b(?:u\.?s\.?|united states) citizenship (?:is )?required",
    r"must be (?:a )?(?:u\.?s\.?|united states) citizen",
    r"(?:active|current).{0,20}security clearance",
    r"requires? .{0,20}security clearance",
]
_NO_SPONSORSHIP_RE = re.compile("|".join(_NO_SPONSORSHIP_PATTERNS), re.IGNORECASE)


def jd_says_no_sponsorship(description: str) -> bool:
    """True if the full JD explicitly rules out visa sponsorship (or requires
    US citizenship / security clearance, which implies it)."""
    return bool(_NO_SPONSORSHIP_RE.search(description or ""))


# ── 2. Score job against resume using Claude ─────────────────

def score_job(job: dict, resume: str) -> tuple[int, list, str]:
    """Return (ats_score, missing_keywords, sponsorship) where sponsorship is
    one of 'yes' | 'no' | 'unknown' based on the job description."""
    prompt = f"""Score how well this job matches the resume on a scale of 0-100 for ATS keyword alignment.
Also classify visa sponsorship based ONLY on the job description text:
  - "no"  : the JD explicitly rules out sponsorship — e.g. "no visa sponsorship",
            "not able to sponsor", "must be authorized to work without sponsorship",
            "US citizenship required", "GC/USC only", or an active security
            clearance requirement (which requires US citizenship).
  - "yes" : the JD explicitly offers sponsorship — e.g. "visa sponsorship available",
            "will sponsor", "open to H1B/OPT/CPT/visa candidates".
  - "unknown" : the JD does not mention work authorization or sponsorship at all.

RESUME:
{resume[:3000]}

JOB TITLE: {job.get('title', '')}
COMPANY: {job.get('company', '')}
JOB DESCRIPTION:
{job.get('description', '')[:2000]}

Reply with ONLY a JSON object:
{{"score": <number>, "missing_keywords": ["kw1", "kw2"], "sponsorship": "yes|no|unknown"}}
"""
    try:
        raw = claude_chat(prompt, system="You are an ATS scoring expert. Reply only with valid JSON.")
        data = parse_json_response(raw)
        sponsorship = str(data.get("sponsorship", "unknown")).strip().lower()
        if sponsorship not in ("yes", "no", "unknown"):
            sponsorship = "unknown"
        return int(data.get("score", 50)), data.get("missing_keywords", []), sponsorship
    except Exception:
        return 50, [], "unknown"


# ── 3. Main pipeline ─────────────────────────────────────────

def run():
    resume = load_resume()
    added = 0
    skipped = 0
    skipped_sponsorship = 0
    skipped_company = 0
    skipped_location = 0

    for role in TARGET_ROLES:
        try:
            jobs = scrape_jobs(role, "United States", max_results=10)
        except Exception as e:
            log(f"  ✗ Scrape failed for '{role}': {e}")
            continue

        log(f"  Found {len(jobs)} listings for '{role}'")

        for job in jobs:
            # curious_coder actor fields: link / title / companyName / descriptionText.
            # Keep the legacy fallbacks so older/alternate actors still work.
            url = job.get("link") or job.get("jobUrl") or job.get("url") or job.get("applyUrl") or ""
            title = job.get("title") or job.get("positionName") or role
            company = job.get("companyName") or job.get("company") or ""
            location = job.get("location") or job.get("formattedLocation") or job.get("jobLocation") or ""
            description = (job.get("descriptionText") or job.get("descriptionHtml")
                           or job.get("description") or job.get("jobDescription") or "")

            if not url:
                continue

            # Skip denylisted companies (services/consulting/staffing) — before
            # scoring so we don't spend an API call on jobs we'll discard.
            if is_skipped_company(company):
                skipped_company += 1
                log(f"  ⊘ Skipped (non-product company): {company} — {title}")
                continue

            # Skip non-US locations
            if not is_us_location(location):
                skipped_location += 1
                log(f"  ⊘ Skipped (non-US location: {location}): {company} — {title}")
                continue

            # Skip duplicates
            existing = db_find_job_by_url(url)
            if existing:
                skipped += 1
                continue

            # Score it (also classifies visa sponsorship from the JD)
            score, missing, sponsorship = score_job({
                "title": title,
                "company": company,
                "description": description,
            }, resume)

            # Skip jobs that explicitly rule out sponsorship (keep yes + unknown)
            if EXCLUDE_NO_SPONSORSHIP and sponsorship == "no":
                skipped_sponsorship += 1
                log(f"  ⊘ Skipped (no sponsorship): {company} — {title}")
                continue

            # Add to Supabase (+ Notion mirror if key set)
            db_add_job({
                "title":     title,
                "company":   company,
                "location":  location,
                "url":       url,
                "ats_score": score,
            })
            added += 1
            log(f"  ✓ Added: {company} — {title} ({location}) (ATS: {score})")

        time.sleep(2)  # polite pause between role queries

    log(f"\nDone. Added {added} new jobs. Skipped {skipped} duplicates, "
        f"{skipped_company} non-product companies, {skipped_location} non-US locations, "
        f"{skipped_sponsorship} for no sponsorship.")
    log(f"View your tracker: https://www.notion.so/{NOTION_DB_ID.replace('-', '')}")


if __name__ == "__main__":
    run()
