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
from scripts.utils import (
    claude_chat, parse_json_response, load_resume, db_add_job, db_add_job_linked,
    db_find_job_by_url, get_notion_jobs_by_status, _notion_promote_to_scraped,
    log, today,
)

# Apify REST API addresses actors as username~actorname (NOT username/actorname,
# which 404s). curious_coder~linkedin-jobs-scraper is the LinkedIn jobs scraper.
APIFY_ACTOR = "curious_coder~linkedin-jobs-scraper"
APIFY_BASE  = "https://api.apify.com/v2"


# ── 1. Scrape LinkedIn via Apify ─────────────────────────────

def _apify_run(urls: list[str], count: int) -> list[dict]:
    """Run the Apify LinkedIn scraper for the given search/job URLs and return
    the dataset items. Polls up to 30×10s until the run finishes."""
    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs"
    payload = {
        # Actor schema: `urls` (array of LinkedIn search/job URLs) + `count` (min 10).
        "urls": urls,
        "count": max(count, 10),
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


def scrape_jobs(role: str, city: str, max_results: int = 10) -> list[dict]:
    log(f"Scraping LinkedIn for: '{role}' in '{city}'")
    search_url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={requests.utils.quote(role)}"
        f"&location={requests.utils.quote(city)}&f_TPR=r86400"
    )
    return _apify_run([search_url], max_results)


# ── LinkedIn job-id helpers (match Apify items back to requested URLs) ──

# Prefer an explicit job-id marker; only fall back to a standalone long number
# that is its own path segment (delimited), never digits buried in query params.
_JOB_ID_RE = re.compile(r"(?:jobs/view/|currentJobId=|/view/)(\d+)")
_JOB_ID_FALLBACK_RE = re.compile(r"/(\d{8,})(?:[/?#]|$)")


def _linkedin_job_id(url: str) -> str:
    """Extract the numeric LinkedIn job id from a job URL, or '' if none."""
    url = url or ""
    m = _JOB_ID_RE.search(url)
    if m:
        return m.group(1)
    m = _JOB_ID_FALLBACK_RE.search(url)
    return m.group(1) if m else ""


def scrape_job_urls(urls: list[str]) -> dict[str, dict]:
    """Enrich individual job-view URLs via one Apify run. Returns a map keyed by
    the original requested URL → {title, company, location, description}. URLs
    that Apify can't resolve are simply absent from the map."""
    if not urls:
        return {}
    try:
        items = _apify_run(urls, len(urls))
    except Exception as e:
        log(f"  ✗ Apify enrichment failed: {e}")
        return {}

    # Index returned items by LinkedIn job id
    by_id = {}
    for job in items:
        item_url = job.get("link") or job.get("jobUrl") or job.get("url") or ""
        jid = _linkedin_job_id(item_url)
        if jid:
            by_id[jid] = job

    enriched = {}
    for url in urls:
        job = by_id.get(_linkedin_job_id(url))
        if not job:
            continue
        enriched[url] = {
            "title":       job.get("title") or job.get("positionName") or "",
            "company":     job.get("companyName") or job.get("company") or "",
            "location":    job.get("location") or job.get("formattedLocation") or job.get("jobLocation") or "",
            "description": (job.get("descriptionText") or job.get("descriptionHtml")
                           or job.get("description") or job.get("jobDescription") or ""),
        }
    return enriched


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


# ── 2. Score jobs against resume using Claude (batched) ──────

def score_jobs_batch(jobs: list[dict], resume: str) -> list[dict]:
    """Score all jobs in a single API call.

    Returns a list of dicts keyed by url:
      {url, score, missing_keywords, sponsorship}
    Falls back to defaults for any entry that can't be parsed.
    """
    if not jobs:
        return []

    job_list = "\n\n".join(
        f"{i+1}. URL: {j['url']}\n"
        f"   Title: {j.get('title','')}\n"
        f"   Company: {j.get('company','')}\n"
        f"   Description: {j.get('description','')[:1500]}"
        for i, j in enumerate(jobs)
    )

    prompt = f"""Score each job below against the resume on a 0-100 ATS keyword alignment scale.
Also classify visa sponsorship for each:
  - "no"      : JD explicitly rules out sponsorship (no visa sponsorship, must be authorized
                without sponsorship, US citizenship required, security clearance required, etc.)
  - "yes"     : JD explicitly offers sponsorship
  - "unknown" : JD does not mention work authorization

RESUME:
{resume[:3000]}

JOBS TO SCORE:
{job_list}

Reply with ONLY a JSON array, one entry per job, in the same order:
[
  {{"url": "...", "score": <0-100>, "missing_keywords": ["kw1", "kw2"], "sponsorship": "yes|no|unknown"}},
  ...
]"""
    try:
        raw = claude_chat(prompt, system="You are an ATS scoring expert. Reply only with a valid JSON array.")
        data = parse_json_response(raw)
        # parse_json_response returns a dict for objects; handle array wrapped in object too
        if isinstance(data, dict):
            # model may have returned {"results": [...]}
            for key in ("results", "jobs", "scores"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError("Expected JSON array")
        # Index by url for fast lookup
        by_url = {entry.get("url", ""): entry for entry in data if isinstance(entry, dict)}
        results = []
        for job in jobs:
            entry = by_url.get(job["url"], {})
            sponsorship = str(entry.get("sponsorship", "unknown")).strip().lower()
            if sponsorship not in ("yes", "no", "unknown"):
                sponsorship = "unknown"
            results.append({
                "url":              job["url"],
                "score":            int(entry.get("score", 50)),
                "missing_keywords": entry.get("missing_keywords", []),
                "sponsorship":      sponsorship,
            })
        return results
    except Exception:
        # Full fallback — give every job a neutral score
        return [{"url": j["url"], "score": 50, "missing_keywords": [], "sponsorship": "unknown"} for j in jobs]


# ── 2b. Ingest manually-added "Interested" jobs from Notion ──

def ingest_interested_from_notion(resume: str) -> int:
    """Pull jobs the user marked 'Interested' in Notion, enrich their JD via
    Apify, score them, and promote them to 'Scraped' (linked to the existing
    Notion page). Hand-picked jobs bypass the company/location/sponsorship
    filters. Returns the number of jobs ingested."""
    pages = get_notion_jobs_by_status("Interested")
    if not pages:
        return 0

    log(f"  Found {len(pages)} 'Interested' job(s) in Notion")

    # Split out URLs already in the DB — just retire their Notion page.
    fresh = []
    for page in pages:
        if db_find_job_by_url(page["url"]):
            log(f"  ⊘ Already in DB, retiring Notion row: {page['url']}")
            _notion_promote_to_scraped(page["notion_page_id"], page)
            continue
        fresh.append(page)

    if not fresh:
        return 0

    # One Apify run to enrich all fresh URLs with real title/company/JD.
    enriched = scrape_job_urls([p["url"] for p in fresh])

    candidates = []
    for page in fresh:
        e = enriched.get(page["url"], {})
        candidates.append({
            "url":            page["url"],
            "notion_page_id": page["notion_page_id"],
            "title":          e.get("title") or page["title"],
            "company":        e.get("company") or page["company"],
            "location":       e.get("location") or page["location"],
            "description":    e.get("description", ""),
        })

    log(f"  Scoring {len(candidates)} Interested job(s) in one batch call…")
    score_by_url = {s["url"]: s for s in score_jobs_batch(candidates, resume)}

    ingested = 0
    for job in candidates:
        s = score_by_url.get(job["url"], {"score": 50})
        db_add_job_linked({
            "title":       job["title"],
            "company":     job["company"],
            "location":    job["location"],
            "url":         job["url"],
            "ats_score":   s["score"],
            "description": job["description"],
        }, job["notion_page_id"])
        ingested += 1
        log(f"  ✓ Ingested: {job['company']} — {job['title']} (ATS: {s['score']})")

    return ingested


# ── 3. Main pipeline ─────────────────────────────────────────

def run():
    resume = load_resume()
    added = 0
    skipped = 0
    skipped_sponsorship = 0
    skipped_company = 0
    skipped_location = 0

    # First, fold in any jobs the user hand-picked in Notion (Status=Interested)
    try:
        ingested = ingest_interested_from_notion(resume)
    except Exception as e:
        log(f"  ✗ Notion ingestion failed: {e}")
        ingested = 0

    for role in TARGET_ROLES:
        try:
            jobs = scrape_jobs(role, "United States", max_results=10)
        except Exception as e:
            log(f"  ✗ Scrape failed for '{role}': {e}")
            continue

        log(f"  Found {len(jobs)} listings for '{role}'")

        # Normalise Apify fields and pre-filter before scoring
        candidates = []
        for job in jobs:
            url = job.get("link") or job.get("jobUrl") or job.get("url") or job.get("applyUrl") or ""
            title = job.get("title") or job.get("positionName") or role
            company = job.get("companyName") or job.get("company") or ""
            location = job.get("location") or job.get("formattedLocation") or job.get("jobLocation") or ""
            description = (job.get("descriptionText") or job.get("descriptionHtml")
                           or job.get("description") or job.get("jobDescription") or "")

            if not url:
                continue
            if is_skipped_company(company):
                skipped_company += 1
                log(f"  ⊘ Skipped (non-product company): {company} — {title}")
                continue
            if not is_us_location(location):
                skipped_location += 1
                log(f"  ⊘ Skipped (non-US location: {location}): {company} — {title}")
                continue
            if db_find_job_by_url(url):
                skipped += 1
                continue

            candidates.append({
                "url": url, "title": title, "company": company,
                "location": location, "description": description,
            })

        if not candidates:
            time.sleep(2)
            continue

        # Score all candidates in a single API call
        log(f"  Scoring {len(candidates)} new job(s) in one batch call…")
        scores = score_jobs_batch(candidates, resume)
        score_by_url = {s["url"]: s for s in scores}

        for job in candidates:
            s = score_by_url.get(job["url"], {"score": 50, "missing_keywords": [], "sponsorship": "unknown"})
            score, sponsorship = s["score"], s["sponsorship"]

            if EXCLUDE_NO_SPONSORSHIP and sponsorship == "no":
                skipped_sponsorship += 1
                log(f"  ⊘ Skipped (no sponsorship): {job['company']} — {job['title']}")
                continue

            # Persist description so Stage 2/5 can skip re-fetching it via AI
            db_add_job({
                "title":       job["title"],
                "company":     job["company"],
                "location":    job["location"],
                "url":         job["url"],
                "ats_score":   score,
                "description": job["description"],
            })
            added += 1
            log(f"  ✓ Added: {job['company']} — {job['title']} ({job['location']}) (ATS: {score})")

        time.sleep(2)  # polite pause between role queries

    log(f"\nDone. Added {added} new jobs ({ingested} ingested from Notion 'Interested'). "
        f"Skipped {skipped} duplicates, {skipped_company} non-product companies, "
        f"{skipped_location} non-US locations, {skipped_sponsorship} for no sponsorship.")
    log(f"View your tracker: https://www.notion.so/{NOTION_DB_ID.replace('-', '')}")


if __name__ == "__main__":
    run()
