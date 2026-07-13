#!/usr/bin/env python3
"""
stage1_scrape.py — Scrape fresh LinkedIn + Indeed jobs & log to Notion
───────────────────────────────────────────────────────────────────────
What it does:
  1. Runs Apify LinkedIn scraper (valig~linkedin-jobs-scraper, 25/role)
     + Indeed scraper (misceres~indeed-scraper, 25/role) for each target role
  2. Applies a 3-layer pre-filter BEFORE scoring (saves API cost):
       a. Company name exact denylist  (SKIP_COMPANIES)
       b. Company name keyword filter  (SKIP_COMPANY_KEYWORDS)
       c. Job title keyword filter     (SKIP_TITLE_KEYWORDS)
       d. US-location check
       e. Deterministic no-sponsorship regex on the full JD
  3. Scores surviving candidates in one batched AI call (ATS + sponsorship)
  4. Skips duplicates already in Notion
  5. Adds new jobs to the Notion tracker with Status = "Scraped"

Run:  python scripts/stage1_scrape.py
"""

import sys, time, re, requests, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat, parse_json_response, load_resume, db_add_job, db_add_job_linked,
    db_find_job_by_url, db_get_all_jobs, get_notion_jobs_by_status,
    _notion_promote_to_scraped, log, today, matches_company_list,
)

APIFY_BASE = "https://api.apify.com/v2"

# ── Apify actors ─────────────────────────────────────────────
# valig~linkedin-jobs-scraper: pay-per-event (~$0.0004/result), no cookie required,
# returns applicationsCount + salary without a Premium session (see Step 1 spike:
# docs/refinement-plans/sourcing/scraping-sources.md). Replaces bebity's $29.99/mo
# rental, whose payload never matched its schema (see git history for the bug).
LINKEDIN_ACTOR = "valig~linkedin-jobs-scraper"
# misceres~indeed-scraper: maintained successor to the deprecated bebity Indeed actor.
INDEED_ACTOR   = "misceres~indeed-scraper"

# Per-role result caps (free Apify tier: ~5 CU/month, each run ~0.05–0.10 CU)
LINKEDIN_MAX = 25
INDEED_MAX   = 25


# ── Generic Apify runner ─────────────────────────────────────

def _apify_run(actor: str, payload: dict, poll: int = 40) -> list[dict]:
    """Start an Apify actor run, poll until done, return dataset items."""
    run_url = f"{APIFY_BASE}/acts/{actor}/runs"
    r = requests.post(run_url, json=payload, params={"token": APIFY_API_TOKEN})
    r.raise_for_status()
    run_id = r.json()["data"]["id"]

    for _ in range(poll):
        time.sleep(10)
        status_r = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}",
            params={"token": APIFY_API_TOKEN},
        )
        status = status_r.json()["data"]["status"]
        log(f"  Apify [{actor}] status: {status}")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Apify run {status}")

    dataset_id = status_r.json()["data"]["defaultDatasetId"]
    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items",
        params={"token": APIFY_API_TOKEN},
    )
    return items_r.json() or []


# ── 1a. LinkedIn scraper (bebity~linkedin-jobs-scraper) ──────

def _linkedin_payload_base(role: str, max_results: int) -> dict:
    """Build the valig~linkedin-jobs-scraper payload.
    No cookie field exists in this actor's schema — applicationsCount and salary
    come back without a Premium session (confirmed via live Step 1 spike run)."""
    return {
        "title":      role,
        "location":   "United States",
        "datePosted": "r86400",  # past 24 hours
        "limit":      max_results,
    }


def _parse_salary(job: dict) -> str:
    """Extract a human-readable salary string from any field the actor returns."""
    for key in ("salaryRange", "salary", "compensationRange", "pay"):
        val = job.get(key)
        if val:
            if isinstance(val, dict):
                lo = val.get("min") or val.get("from") or val.get("low") or ""
                hi = val.get("max") or val.get("to")   or val.get("high") or ""
                if lo or hi:
                    return f"{lo}–{hi}".strip("–")
            return str(val)
    return ""


def scrape_linkedin(role: str, max_results: int = LINKEDIN_MAX) -> list[dict]:
    """Scrape LinkedIn for `role` posted in the last 24 h.
    With a Premium cookie, also captures applicant_count and salary_range."""
    log(f"  [LinkedIn] Scraping: '{role}'")
    payload = _linkedin_payload_base(role, max_results)
    try:
        items = _apify_run(LINKEDIN_ACTOR, payload)
    except Exception as e:
        log(f"  ✗ LinkedIn scrape failed for '{role}': {e}")
        return []

    results = []
    for job in items:
        url = (
            job.get("jobUrl") or job.get("link") or
            job.get("url")    or job.get("applyUrl") or ""
        )
        if not url:
            continue

        # Applicant count — valig returns a phrase like "Over 200 applicants", not a bare int
        raw_count = (job.get("applicationsCount") or job.get("applicantCount")
                    or job.get("applicantsCount")  or job.get("numApplicants"))
        applicant_count = None
        if raw_count:
            m = re.search(r"\d[\d,]*", str(raw_count))
            if m:
                try:
                    applicant_count = int(m.group(0).replace(",", ""))
                except ValueError:
                    applicant_count = None

        results.append({
            "url":             url,
            "title":           job.get("title") or job.get("positionName") or role,
            "company":         job.get("companyName") or job.get("company") or "",
            "location":        (job.get("location") or job.get("formattedLocation")
                                or job.get("jobLocation") or ""),
            "description":     (job.get("description") or job.get("descriptionText")
                                or job.get("descriptionHtml")  or job.get("jobDescription") or ""),
            "applicant_count": applicant_count,
            "salary_range":    _parse_salary(job),
            "source":          "linkedin",
        })
    log(f"  [LinkedIn] Got {len(results)} listings for '{role}'")
    return results


# ── 1b. Indeed scraper (bebity~indeed-scraper) ───────────────

def scrape_indeed(role: str, max_results: int = INDEED_MAX) -> list[dict]:
    """Scrape Indeed for `role` in the US posted in the last day."""
    log(f"  [Indeed] Scraping: '{role}'")
    payload = {
        "position":            role,
        "country":             "US",  # misceres validates a strict uppercase enum
        "location":            "",          # blank = nationwide
        "maxItemsPerSearch":   max_results,
        "parseCompanyDetails": False,
        "saveOnlyUniqueItems": True,
        "followApplyRedirects": False,
    }
    try:
        items = _apify_run(INDEED_ACTOR, payload)
    except Exception as e:
        log(f"  ✗ Indeed scrape failed for '{role}': {e}")
        return []

    results = []
    for job in items:
        url = (
            job.get("url") or job.get("jobUrl") or
            job.get("externalApplyLink") or ""
        )
        if not url:
            continue
        results.append({
            "url":         url,
            "title":       job.get("positionName") or job.get("title") or role,
            "company":     job.get("company") or "",
            "location":    job.get("location") or "",
            "description": job.get("description") or "",
            "source":      "indeed",
        })
    log(f"  [Indeed] Got {len(results)} listings for '{role}'")
    return results


# ── 1c. Enrich individual LinkedIn job URLs (for Notion intake) ──

_JOB_ID_RE          = re.compile(r"(?:jobs/view/|currentJobId=|/view/)(\d+)")
_JOB_ID_FALLBACK_RE = re.compile(r"/(\d{8,})(?:[/?#]|$)")


def _linkedin_job_id(url: str) -> str:
    url = url or ""
    m = _JOB_ID_RE.search(url)
    if m:
        return m.group(1)
    m = _JOB_ID_FALLBACK_RE.search(url)
    return m.group(1) if m else ""


def scrape_job_urls(urls: list[str]) -> dict[str, dict] | None:
    """Enrich individual LinkedIn job-view URLs via one Apify run.
    Returns a map: original URL → {title, company, location, description}.
    Returns None if the Apify call itself failed (distinct from a successful call that
    enriched zero URLs, which returns {})."""
    if not urls:
        return {}
    payload = {
        "urls":          urls,
        "count":         max(len(urls), 10),
        "scrapeCompany": False,
    }
    try:
        # Fall back to the reliable url-based actor for enrichment
        items = _apify_run("curious_coder~linkedin-jobs-scraper", payload)
    except Exception as e:
        log(f"  ✗ Apify enrichment failed: {e}")
        return None

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
            "location":    (job.get("location") or job.get("formattedLocation")
                            or job.get("jobLocation") or ""),
            "description": (job.get("descriptionText") or job.get("descriptionHtml")
                            or job.get("description") or job.get("jobDescription") or ""),
        }
    if not enriched:
        log(f"  ⚠ Apify call succeeded but matched 0 of {len(urls)} URL(s) to results")
    return enriched


# ── 2. Filters ────────────────────────────────────────────────

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
        return True  # keep unknowns — boards often omit location for remote roles
    return bool(_US_LOCATION_RE.search(location))


def is_skipped_company(company: str) -> bool:
    """Two-layer check:
    1. Word-boundary token sub-sequence match against SKIP_COMPANIES — not a substring
       match, so short entries (e.g. "UST", "Dice") can't false-positive inside unrelated
       names ("Customer.io", "Indices").
    2. Substring/phrase match against SKIP_COMPANY_KEYWORDS (catches unnamed firms)
    """
    name = (company or "").lower().strip()
    if not name:
        return False
    # Layer 1 — named denylist
    if matches_company_list(name, SKIP_COMPANIES):
        return True
    # Layer 2 — keyword patterns
    if any(kw.lower() in name for kw in SKIP_COMPANY_KEYWORDS):
        return True
    return False


def is_skipped_title(title: str) -> bool:
    """True if the job title contains a keyword that signals a
    consulting/staffing/non-product role."""
    t = (title or "").lower()
    return any(kw.lower() in t for kw in SKIP_TITLE_KEYWORDS)


# ── 3. Deterministic no-sponsorship check (scans full JD) ────
_NO_SPONSORSHIP_PATTERNS = [
    r"will not sponsor",
    r"\bnot\s+sponsor(?:ing)?\b",
    r"do(?:es)?\s+not\s+(?:provide|offer|support|consider).{0,50}sponsor",
    r"(?:un)?able\s+to\s+sponsor",
    r"not\s+(?:be\s+)?(?:able|eligible|in\s+a\s+position)\s+to\s+sponsor",
    r"no\s+(?:visa\s+)?sponsorship(?:\s+available| provided| offered)?",
    r"sponsorship\s+(?:is\s+)?not\s+(?:available|offered|provided|possible)",
    r"without\s+(?:the\s+need\s+for\s+)?(?:visa\s+|employer\s+)?sponsorship",
    r"authoriz(?:ed|ation)\s+to\s+work.{0,60}without\s+(?:visa\s+)?sponsorship",
    r"do(?:es)?\s+not\s+(?:provide|offer|support).{0,50}immigration",
    r"cannot\s+(?:provide|offer|support).{0,50}(?:sponsor|visa|immigration)",
    r"\b(?:u\.?s\.?|united\s+states)\s+citizenship\s+(?:is\s+)?required",
    r"must\s+be\s+(?:a\s+)?(?:u\.?s\.?|united\s+states)\s+citizen",
    r"must\s+be\s+(?:authorized|eligible)\s+to\s+work\s+(?:in\s+the\s+us|in\s+the\s+united\s+states)\s+without",
    r"work\s+authorization\s+(?:is\s+)?required\s+(?:and\s+)?(?:we\s+)?(?:do\s+not|cannot|will\s+not)\s+sponsor",
    r"(?:active|current|valid).{0,30}(?:ts|secret|top\s+secret)\s+clearance",
    r"(?:active|current).{0,20}security\s+clearance",
    r"requires?\s+.{0,20}security\s+clearance",
    r"must\s+(?:hold|have|possess|maintain).{0,30}clearance",
    r"green\s+card\s+(?:or\s+)?(?:u\.?s\.?\s+)?citizenship\s+required",
]
_NO_SPONSORSHIP_RE = re.compile("|".join(_NO_SPONSORSHIP_PATTERNS), re.IGNORECASE)


def jd_says_no_sponsorship(description: str) -> bool:
    """True if the full JD explicitly rules out visa sponsorship."""
    return bool(_NO_SPONSORSHIP_RE.search(description or ""))


# ── 4. AI scoring (batched) ───────────────────────────────────

def _jd_excerpt(desc: str, head: int = 1200, tail: int = 800) -> str:
    """Keep the head AND tail of a long JD instead of truncating from the top only —
    work-authorization/EEO boilerplate typically lives in the legal block at the bottom."""
    desc = desc or ""
    if len(desc) <= head + tail:
        return desc
    return f"{desc[:head]}\n…[trimmed]…\n{desc[-tail:]}"


def score_jobs_batch(jobs: list[dict], resume: str) -> list[dict]:
    """Score all jobs in a single AI call → [{url, score, missing_keywords, sponsorship}].
    Sponsorship classification here is a second-pass safety net; the deterministic
    regex catches the clear cases before we even reach scoring."""
    if not jobs:
        return []

    job_list = "\n\n".join(
        f"{i+1}. URL: {j['url']}\n"
        f"   Title: {j.get('title','')}\n"
        f"   Company: {j.get('company','')}\n"
        f"   Description: {_jd_excerpt(j.get('description',''))}"
        for i, j in enumerate(jobs)
    )

    prompt = f"""Score each job below against the resume on a 0-100 ATS keyword alignment scale.

Also classify visa sponsorship:
  "no"      — JD explicitly rules out sponsorship (no visa sponsorship, must be authorized
               without sponsorship, US citizenship required, security clearance required, etc.)
  "yes"     — JD explicitly offers or mentions sponsorship
  "unknown" — JD is silent on work authorization

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
        if isinstance(data, dict):
            for key in ("results", "jobs", "scores"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError("Expected JSON array")
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
        return [{"url": j["url"], "score": 50, "missing_keywords": [], "sponsorship": "unknown"} for j in jobs]


# ── 5. Ingest manually-added "Interested" jobs from Notion ───

def ingest_interested_from_notion(resume: str) -> int:
    """Pull jobs the user marked 'Interested' in Notion, enrich via Apify,
    score, and promote to 'Scraped'. Hand-picked jobs bypass all filters."""
    pages = get_notion_jobs_by_status("Interested")
    if not pages:
        return 0

    log(f"  Found {len(pages)} 'Interested' job(s) in Notion")

    fresh = []
    for page in pages:
        if db_find_job_by_url(page["url"], exclude_page_id=page["notion_page_id"]):
            log(f"  ⊘ Already in DB, retiring Notion row: {page['url']}")
            _notion_promote_to_scraped(page["notion_page_id"], page)
            continue
        fresh.append(page)

    if not fresh:
        return 0

    enriched = scrape_job_urls([p["url"] for p in fresh])
    if enriched is None:
        log("  ✗ Enrichment failed for all Interested jobs this run — leaving them as-is for the next run")
        return 0

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
            "applicant_count": None,
            "salary_range":    "",
        })

    log(f"  Scoring {len(candidates)} Interested job(s) in one batch call...")
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


# ── 6. Drop-log writer ───────────────────────────────────────

def _open_drop_log():
    """Create today's drop log file. Returns (path, file handle)."""
    log_dir = Path(OUTPUT_DIR) / "filter_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path   = log_dir / f"dropped_{run_ts}.txt"
    fh     = path.open("w", encoding="utf-8")
    fh.write(f"Drop log — run started {run_ts}\n")
    fh.write("=" * 70 + "\n\n")
    return path, fh


def _log_drop(fh, reason: str, job: dict) -> None:
    """Append one dropped-job record to the open drop log."""
    fh.write(
        f"[{reason.upper()}]\n"
        f"  Company   : {job.get('company', '')}\n"
        f"  Title     : {job.get('title', '')}\n"
        f"  Location  : {job.get('location', '')}\n"
        f"  Applicants: {job.get('applicant_count', '')}\n"
        f"  Salary    : {job.get('salary_range', '')}\n"
        f"  Source    : {job.get('source', '')}\n"
        f"  URL       : {job.get('url', '')}\n\n"
    )


# ── 7. Pre-filter helper ─────────────────────────────────────

def _pre_filter(job: dict, seen_urls: set, existing_urls: set, counters: dict, drop_fh) -> bool:
    """Apply all pre-scoring filters. Returns True if job should be kept.

    `seen_urls` dedups within this run; `existing_urls` is a one-shot snapshot of every
    URL already in Notion, so the two together cover this run and all prior ones."""
    url             = job.get("url", "")
    title           = job.get("title", "")
    company         = job.get("company", "")
    location        = job.get("location", "")
    description     = job.get("description", "")
    applicant_count = job.get("applicant_count")

    if not url:
        return False
    if url in seen_urls:
        return False
    if is_skipped_company(company):
        counters["company"] += 1
        _log_drop(drop_fh, "company", job)
        log(f"  ⊘ [company]       {company} — {title}")
        return False
    if is_skipped_title(title):
        counters["title"] += 1
        _log_drop(drop_fh, "title", job)
        log(f"  ⊘ [title]         {company} — {title}")
        return False
    if not is_us_location(location):
        counters["location"] += 1
        _log_drop(drop_fh, "location", job)
        log(f"  ⊘ [location]      {company} — {title} ({location})")
        return False
    if EXCLUDE_NO_SPONSORSHIP and jd_says_no_sponsorship(description):
        counters["sponsorship"] += 1
        _log_drop(drop_fh, "no-sponsor", job)
        log(f"  ⊘ [no-sponsor]    {company} — {title}")
        return False
    if MAX_APPLICANT_COUNT and applicant_count and applicant_count > MAX_APPLICANT_COUNT:
        counters["applicants"] += 1
        _log_drop(drop_fh, "high-applicants", job)
        log(f"  ⊘ [high-applicants] {company} — {title} ({applicant_count} applicants)")
        return False
    if url in existing_urls:
        counters["duplicate"] += 1
        return False
    return True


# ── 8. Main pipeline ─────────────────────────────────────────

def run():
    resume   = load_resume()
    added    = 0
    ingested = 0
    counters = {
        "company": 0, "title": 0, "location": 0,
        "sponsorship": 0, "applicants": 0, "duplicate": 0, "low_score": 0,
    }

    drop_log_path, drop_fh = _open_drop_log()

    # 8a. Ingest hand-picked Notion jobs
    try:
        ingested = ingest_interested_from_notion(resume)
    except Exception as e:
        log(f"  ✗ Notion ingestion failed: {e}")

    # 8a-bis. One-shot Notion snapshot for dedup (replaces per-job db_find_job_by_url).
    # Taken after ingestion so freshly-promoted "Interested" rows are included. Excludes
    # not-yet-settled statuses (Interested, and future Retry) so a queued row doesn't dedup
    # against itself.
    UNSETTLED_STATUSES = {"Interested"}
    existing_jobs = db_get_all_jobs()
    existing_urls = {j["url"] for j in existing_jobs if j["url"] and j["status"] not in UNSETTLED_STATUSES}
    log(f"  Notion snapshot: {len(existing_urls)} existing job URL(s)")

    # 8b. Scrape LinkedIn + Indeed for each target role
    seen_urls: set = set()

    for role in TARGET_ROLES:
        log(f"\n── Role: {role} ──────────────────────────────")
        drop_fh.write(f"\n{'-'*60}\nROLE: {role}\n{'-'*60}\n\n")

        raw_jobs = []
        raw_jobs.extend(scrape_linkedin(role, LINKEDIN_MAX))
        raw_jobs.extend(scrape_indeed(role, INDEED_MAX))
        log(f"  Total raw listings: {len(raw_jobs)}")

        candidates = []
        for job in raw_jobs:
            if job["url"] in seen_urls:
                counters["duplicate"] += 1
                continue
            if _pre_filter(job, seen_urls, existing_urls, counters, drop_fh):
                seen_urls.add(job["url"])
                candidates.append(job)

        if not candidates:
            log(f"  No candidates survived pre-filter for '{role}'")
            time.sleep(2)
            continue

        log(f"  Scoring {len(candidates)} candidate(s)...")
        scores       = score_jobs_batch(candidates, resume)
        score_by_url = {s["url"]: s for s in scores}

        for job in candidates:
            s           = score_by_url.get(job["url"], {"score": 50, "missing_keywords": [], "sponsorship": "unknown"})
            score       = s["score"]
            sponsorship = s["sponsorship"]

            if EXCLUDE_NO_SPONSORSHIP and sponsorship == "no":
                counters["sponsorship"] += 1
                _log_drop(drop_fh, "no-sponsor/AI", job)
                log(f"  ⊘ [no-sponsor/AI]  {job['company']} — {job['title']}")
                continue

            if MIN_ATS_SCORE and score < MIN_ATS_SCORE:
                counters["low_score"] += 1
                _log_drop(drop_fh, "low-ats-score", job)
                log(f"  ⊘ [low-ats-score:{score}]  {job['company']} — {job['title']}")
                continue

            ac  = job.get("applicant_count")
            sal = job.get("salary_range", "")
            db_add_job({
                "title":           job["title"],
                "company":         job["company"],
                "location":        job["location"],
                "url":             job["url"],
                "ats_score":       score,
                "description":     job["description"],
                "applicant_count": ac,
                "salary_range":    sal,
            })
            added  += 1
            src     = job.get("source", "")
            ac_str  = f"  applicants:{ac}" if ac  is not None else ""
            sal_str = f"  salary:{sal}"     if sal             else ""
            log(f"  ✓ Added [{src}]: {job['company']} — {job['title']} ({job['location']}) ATS:{score}{ac_str}{sal_str}")

        time.sleep(2)

    summary = (
        f"\n{'-'*60}\n"
        f"Done. Added {added} new job(s)  |  {ingested} ingested from Notion 'Interested'\n"
        f"Pre-filter drops -> "
        f"company:{counters['company']}  title:{counters['title']}  "
        f"location:{counters['location']}  no-sponsor:{counters['sponsorship']}  "
        f"high-applicants:{counters['applicants']}  duplicate:{counters['duplicate']}  "
        f"low-ats-score:{counters['low_score']}\n"
        f"Drop log saved -> {drop_log_path}"
    )
    drop_fh.write(f"\n{'='*70}\nSUMMARY\n{summary}\n")
    drop_fh.close()

    log(summary)
    log(f"View tracker: https://www.notion.so/{NOTION_DB_ID.replace('-', '')}")


if __name__ == "__main__":
    run()
