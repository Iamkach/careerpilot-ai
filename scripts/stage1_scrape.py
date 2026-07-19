#!/usr/bin/env python3
"""
stage1_scrape.py — Scrape fresh jobs from every enabled source & log to Notion
───────────────────────────────────────────────────────────────────────
What it does:
  1. Gathers raw listings from every scripts/sources.py registry entry named in
     ENABLED_SOURCES: keyword sources (LinkedIn, Indeed) per TARGET_ROLES, and board
     sources (Greenhouse, Lever, Ashby) per discovered TARGET_COMPANIES token.
  2. Collapses cross-source duplicates by (company, title) fingerprint — the same req
     posted to LinkedIn AND a company's own Greenhouse board collapses to one row, with
     the ATS-board copy winning (fuller JD, real date, direct-apply URL).
  3. Applies a pre-filter BEFORE scoring (saves API cost):
       a. Freshness (posted_date vs MAX_JOB_AGE_DAYS)
       b. Company name exact denylist  (SKIP_COMPANIES)
       c. Company name keyword filter  (SKIP_COMPANY_KEYWORDS)
       d. Job title keyword filter     (SKIP_TITLE_KEYWORDS)
       e. US-location check
       f. Deterministic no-sponsorship regex on the full JD
       g. Duplicate-of-existing-Notion-row (URL or fingerprint)
  4. Scores surviving candidates in one batched AI call (ATS + sponsorship)
  5. Adds new jobs to the Notion tracker with Status = "Scraped"

Run:  python scripts/stage1_scrape.py
"""

import sys, time, re, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import (
    claude_chat, parse_json_response, load_resume, db_add_job, db_add_job_linked,
    db_find_job_by_url, db_get_all_jobs, db_get_jobs, db_get_job_description,
    db_update_status, get_notion_jobs_by_status,
    get_scratch_note_entries, archive_scratch_note_entry, db_add_interested_url,
    _notion_promote_to_scraped, log, today, matches_company_list,
)
from scripts.sources import (
    KEYWORD_SOURCES, BOARD_SOURCES, job_fingerprint, collapse_by_fingerprint,
    _is_fresh, discover_tokens, _apify_run, enrich_job_url,
)

APIFY_BASE = "https://api.apify.com/v2"


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


_COMPANY_TYPES = ("product", "staffing_or_consulting", "agency", "unknown")


def _unscored(job: dict) -> dict:
    """The scoring contract's failure shape — used both when the whole batch call fails
    (after ai_chat's own retries) and when a specific URL is missing from a successful
    response. Never fabricate a numeric score here (that was the old score=50 bug)."""
    return {
        "url":              job["url"],
        "score":            None,
        "scored":           False,
        "missing_keywords": [],
        "sponsorship":      "unknown",
        "company_type":     "unknown",
    }


_SCORE_CHUNK_SIZE = 20  # keep each AI call's JSON reply well under any provider's default max_tokens


def score_jobs_batch(jobs: list[dict], resume: str) -> list[dict]:
    """Score all jobs, chunked into calls of at most `_SCORE_CHUNK_SIZE` →
    [{url, score, scored, missing_keywords, sponsorship, company_type}].
    A single AI call covering a large candidate list can have its JSON reply truncated by
    the model's max_tokens cap, which fails parsing for the *whole* batch — chunking keeps
    each call's expected output small enough to always fit, and one chunk's failure no
    longer takes down every other candidate's score with it."""
    if not jobs:
        return []
    results = []
    for i in range(0, len(jobs), _SCORE_CHUNK_SIZE):
        results.extend(_score_jobs_chunk(jobs[i:i + _SCORE_CHUNK_SIZE], resume))
    return results


def _score_jobs_chunk(jobs: list[dict], resume: str) -> list[dict]:
    """Score one chunk of jobs in a single AI call. See score_jobs_batch for why chunking
    matters; this function keeps the original single-call scoring logic per chunk.
    On a call that fails outright (ai_chat exhausts its own retries) or a malformed
    response, every job in this chunk comes back `scored: False` — callers must queue
    those for retry, never treat a missing/failed score as a real 0-100 value."""
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

Also classify the hiring company itself:
  "product"                — the company builds/owns its own product(s); this JD is a direct-hire role
  "staffing_or_consulting" — a staffing agency, IT consultancy, or body-shop placing candidates at
                              OTHER companies (e.g. "our client is seeking...", generic bench roles)
  "agency"                 — a recruiting/talent agency filling a role on behalf of a named employer
  "unknown"                — can't tell from the JD

RESUME:
{resume[:3000]}

JOBS TO SCORE:
{job_list}

Reply with ONLY a JSON array, one entry per job, in the same order:
[
  {{"url": "...", "score": <0-100>, "missing_keywords": ["kw1", "kw2"], "sponsorship": "yes|no|unknown",
    "company_type": "product|staffing_or_consulting|agency|unknown"}},
  ...
]"""
    try:
        raw = claude_chat(prompt, system="You are an ATS scoring expert. Reply only with a valid JSON array.",
                           max_tokens=4096)
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
            entry = by_url.get(job["url"])
            if entry is None:
                # Batch call succeeded but this URL wasn't in the response — treat it the
                # same as a scoring failure, not a fabricated score.
                results.append(_unscored(job))
                continue
            sponsorship = str(entry.get("sponsorship", "unknown")).strip().lower()
            if sponsorship not in ("yes", "no", "unknown"):
                sponsorship = "unknown"
            company_type = str(entry.get("company_type", "unknown")).strip().lower()
            if company_type not in _COMPANY_TYPES:
                company_type = "unknown"
            results.append({
                "url":              job["url"],
                "score":            max(0, min(100, int(entry.get("score", 0)))),
                "scored":           True,
                "missing_keywords": entry.get("missing_keywords", []),
                "sponsorship":      sponsorship,
                "company_type":     company_type,
            })
        return results
    except Exception as e:
        log(f"  ✗ score_jobs_batch failed for {len(jobs)} job(s), queuing for retry: {e}")
        return [_unscored(j) for j in jobs]


# ── 5. Ingest manually-added "Interested" jobs from Notion ───

def ingest_from_scratch_note() -> int:
    """Read every row of the scratch-note Notion database (NOTION_SCRATCH_PAGE_ID) — one
    URL per row's title — and create a minimal Status='Interested' row in the Jobs DB for
    each URL not already tracked anywhere. A row is archived out of the scratch database
    once it's been successfully converted (or found to be a duplicate); a row that fails
    to convert is left in place and retried next run. No-op (returns 0) if
    NOTION_SCRATCH_PAGE_ID is unset. Never raises."""
    entries = get_scratch_note_entries()
    if not entries:
        return 0

    log(f"  Found {len(entries)} URL(s) in the scratch note")

    added = 0
    for entry in entries:
        url, page_id = entry["url"], entry["page_id"]
        if db_find_job_by_url(url):
            log(f"  ⊘ Already tracked, dropping from note: {url}")
            archive_scratch_note_entry(page_id)
            continue
        if db_add_interested_url(url):
            added += 1
            log(f"  ✓ Queued Interested row: {url}")
            archive_scratch_note_entry(page_id)
        else:
            log(f"  ✗ Failed to create row, leaving in note for retry: {url}")

    return added


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

    # LinkedIn URLs go through the batched Apify actor; everything else (Greenhouse/Lever/
    # Ashby direct APIs, or a best-effort HTML scrape) has no batch endpoint, so it's
    # enriched one URL at a time via enrich_job_url().
    linkedin_pages = [p for p in fresh if "linkedin.com" in p["url"]]
    other_pages    = [p for p in fresh if "linkedin.com" not in p["url"]]

    enriched: dict[str, dict] = {}
    if linkedin_pages:
        li_enriched = scrape_job_urls([p["url"] for p in linkedin_pages])
        if li_enriched:
            enriched.update(li_enriched)
    for page in other_pages:
        e = enrich_job_url(page["url"])
        if e:
            enriched[page["url"]] = e

    candidates = []
    for page in fresh:
        e = enriched.get(page["url"])
        # No real JD text means nothing to score against — leave the row as "Interested"
        # for the next run rather than writing a confident-looking score off blank input.
        if not e or not e.get("description"):
            log(f"  ⏳ Enrichment failed, leaving as Interested for next run: {page['url']}")
            continue
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

    if not candidates:
        return 0

    log(f"  Scoring {len(candidates)} Interested job(s) in one batch call...")
    score_by_url = {s["url"]: s for s in score_jobs_batch(candidates, resume)}

    ingested = 0
    for job in candidates:
        s = score_by_url.get(job["url"]) or _unscored(job)
        if not s["scored"]:
            # Leave as "Retry" (not "Interested" — it's already enriched/JD-cached, so the
            # top-of-run rescore_retry_jobs() picks it up without a repeat Apify call).
            db_add_job_linked({
                "title":            job["title"],
                "company":          job["company"],
                "location":         job["location"],
                "description":      job["description"],
                "sponsorship":      "unknown",
                "scoring_attempts": 1,
            }, job["notion_page_id"], status="Retry")
            log(f"  ⏳ Queued for retry (scoring failed): {job['company']} — {job['title']}")
            continue
        db_add_job_linked({
            "title":            job["title"],
            "company":          job["company"],
            "location":         job["location"],
            "url":              job["url"],
            "ats_score":        s["score"],
            "sponsorship":      s["sponsorship"],
            "description":      job["description"],
            "missing_keywords": s["missing_keywords"],
        }, job["notion_page_id"])
        ingested += 1
        log(f"  ✓ Ingested: {job['company']} — {job['title']} (ATS: {s['score']})")

    return ingested


# ── 5b. Re-score jobs stuck in "Retry" from a prior failed scoring pass ──

def rescore_retry_jobs(resume: str) -> dict:
    """Re-score every Status='Retry' job from its already-cached JD (no Apify call).
    Returns {"recovered": n, "filtered": n, "given_up": n, "still_retrying": n}.

    A successfully-scored job is subject to the same post-scoring gates the normal scrape
    path in run() applies (EXCLUDE_NO_SPONSORSHIP, SKIP_COMPANY_TYPES, MIN_ATS_SCORE) before
    promotion to 'Scraped' — a job the fresh-scrape path would have silently dropped must not
    survive just because it happened to fail scoring on its first pass and come through this
    recovery path instead. A gated job moves to 'Disregard' (not 'Scraped') with a note
    explaining why, since — unlike a fresh scrape, which simply never writes the page — this
    job's Notion page already exists and needs an explicit terminal status."""
    counters = {"recovered": 0, "filtered": 0, "given_up": 0, "still_retrying": 0}
    pages = db_get_jobs(status="Retry")
    if not pages:
        return counters

    log(f"  Re-scoring {len(pages)} job(s) stuck in 'Retry'...")
    candidates = []
    for page in pages:
        desc = db_get_job_description(page["page_id"])
        candidates.append({**page, "description": desc})

    score_by_url = {s["url"]: s for s in score_jobs_batch(candidates, resume)}

    for job in candidates:
        s = score_by_url.get(job["url"]) or _unscored(job)
        if s["scored"]:
            gate_reason = None
            if EXCLUDE_NO_SPONSORSHIP and s["sponsorship"] == "no":
                gate_reason = "no-sponsor/AI"
            elif s["company_type"] in SKIP_COMPANY_TYPES:
                gate_reason = "staffing/AI"
            elif MIN_ATS_SCORE and s["score"] < MIN_ATS_SCORE:
                gate_reason = f"low-ats-score:{s['score']}"

            if gate_reason:
                db_update_status(job["page_id"], "Disregard", {
                    "ats_score":        s["score"],
                    "sponsorship":      s["sponsorship"],
                    "scoring_attempts": (job.get("scoring_attempts") or 0) + 1,
                    "missing_keywords": s["missing_keywords"],
                    "notes": f"Auto-filtered on recovery from Retry: [{gate_reason}]",
                })
                counters["filtered"] += 1
                log(f"  ⊘ [{gate_reason}] Filtered on recovery: {job['company']} — {job['title']}")
                continue

            db_update_status(job["page_id"], "Scraped", {
                "ats_score":        s["score"],
                "sponsorship":      s["sponsorship"],
                "scoring_attempts": (job.get("scoring_attempts") or 0) + 1,
                "missing_keywords": s["missing_keywords"],
            })
            counters["recovered"] += 1
            log(f"  ✓ Recovered from Retry: {job['company']} — {job['title']} (ATS: {s['score']})")
            continue

        attempts = (job.get("scoring_attempts") or 0) + 1
        if attempts > MAX_SCORING_ATTEMPTS:
            db_update_status(job["page_id"], "Scraped", {
                "scoring_attempts": attempts,
            })
            counters["given_up"] += 1
            log(f"  ⚠ giving up on scoring after {attempts} attempts: "
                f"{job['company']} — {job['title']}")
        else:
            db_update_status(job["page_id"], "Retry", {
                "scoring_attempts": attempts,
            })
            counters["still_retrying"] += 1

    return counters


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

def _pre_filter(job: dict, seen_urls: set, existing_urls: set, existing_fps: set,
                 counters: dict, drop_fh) -> bool:
    """Apply all pre-scoring filters. Returns True if job should be kept.

    `seen_urls`/`existing_fps` dedup within this run and against Notion respectively;
    `existing_urls` is a one-shot snapshot of every URL already in Notion, so the two
    together cover this run and all prior ones."""
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
    if not _is_fresh(job.get("posted_date")):
        counters["stale"] += 1
        _log_drop(drop_fh, "stale", job)
        log(f"  ⊘ [stale]         {company} — {title} (posted {job.get('posted_date')})")
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
    if url in existing_urls or job_fingerprint(company, title) in existing_fps:
        counters["duplicate"] += 1
        return False
    return True


# ── 8. Main pipeline ─────────────────────────────────────────

def run():
    resume   = load_resume()
    added    = 0
    ingested = 0
    counters = {
        "company": 0, "title": 0, "location": 0, "stale": 0,
        "sponsorship": 0, "applicants": 0, "duplicate": 0, "low_score": 0,
        "staffing_ai": 0, "retry": 0,
    }

    drop_log_path, drop_fh = _open_drop_log()

    # 8a-pre. Promote scratch-note URL drops to Interested rows
    try:
        promoted = ingest_from_scratch_note()
        if promoted:
            log(f"  Promoted {promoted} scratch-note URL(s) to Interested")
    except Exception as e:
        log(f"  ✗ Scratch-note ingestion failed: {e}")

    # 8a. Ingest hand-picked Notion jobs
    try:
        ingested = ingest_interested_from_notion(resume)
    except Exception as e:
        log(f"  ✗ Notion ingestion failed: {e}")

    # 8a-bis. Re-score anything still stuck in "Retry" from a prior failed scoring pass,
    # from its already-cached JD — no repeat Apify call.
    try:
        retry_counters = rescore_retry_jobs(resume)
        log(f"  Retry queue: {retry_counters['recovered']} recovered, "
            f"{retry_counters['filtered']} filtered (no-sponsor/staffing/low-score), "
            f"{retry_counters['given_up']} given up, "
            f"{retry_counters['still_retrying']} still retrying")
    except Exception as e:
        log(f"  ✗ Retry-queue rescoring failed: {e}")

    # 8a-ter. One-shot Notion snapshot for dedup (replaces per-job db_find_job_by_url).
    # Taken after ingestion so freshly-promoted "Interested" rows are included. Excludes
    # not-yet-settled statuses (Interested, Retry) so a queued row doesn't dedup
    # against itself. A failed read means dedup state is unknown — abort rather than
    # proceeding as if the DB were empty, which would mass-duplicate the tracker.
    UNSETTLED_STATUSES = {"Interested", "Retry"}
    try:
        existing_jobs = db_get_all_jobs()
    except RuntimeError as e:
        log(f"  ✗ ABORTING scrape — Notion snapshot read failed, dedup state unknown: {e}")
        drop_fh.write(f"\nABORTED: {e}\n")
        drop_fh.close()
        return
    existing_urls = {j["url"] for j in existing_jobs if j["url"] and j["status"] not in UNSETTLED_STATUSES}
    existing_fps  = {
        job_fingerprint(j["company"], j["title"])
        for j in existing_jobs if j["status"] not in UNSETTLED_STATUSES
    }
    log(f"  Notion snapshot: {len(existing_urls)} existing job URL(s), {len(existing_fps)} fingerprint(s)")

    # 8b. Global gather — every enabled keyword source × TARGET_ROLES, plus every enabled
    # board source × discovered TARGET_COMPANIES token. A duplicate can span both roles and
    # sources, so this has to happen before any per-role filtering can see it.
    raw_jobs: list[dict] = []

    for role in TARGET_ROLES:
        log(f"\n── Role: {role} ──────────────────────────────")
        for name in ENABLED_SOURCES:
            fn = KEYWORD_SOURCES.get(name)
            if not fn:
                continue
            raw_jobs.extend(fn(role))
        time.sleep(2)

    enabled_boards = [n for n in ENABLED_SOURCES if n in BOARD_SOURCES]
    if enabled_boards:
        seed_companies = sorted(set(TARGET_COMPANIES) | {j["company"] for j in existing_jobs if j["company"]})
        log(f"\n── ATS boards: {len(seed_companies)} seed compan(y/ies), sources {enabled_boards} ──")
        tokens = discover_tokens(seed_companies)
        for company, entry in tokens.items():
            for board_name in enabled_boards:
                token = entry.get(board_name)
                if not token:
                    continue
                raw_jobs.extend(BOARD_SOURCES[board_name](company, token))

    log(f"\nTotal raw listings across all sources: {len(raw_jobs)}")

    # 8c. Collapse cross-source duplicates (company+title fingerprint) before filtering,
    # so the sponsorship regex and freshness check run against the fullest JD available.
    collapsed = collapse_by_fingerprint(raw_jobs)
    log(f"After fingerprint collapse: {len(collapsed)} unique listing(s)")

    # 8d. Filter
    seen_urls: set = set()
    candidates = []
    for job in collapsed:
        if job["url"] in seen_urls:
            counters["duplicate"] += 1
            continue
        if _pre_filter(job, seen_urls, existing_urls, existing_fps, counters, drop_fh):
            seen_urls.add(job["url"])
            candidates.append(job)

    if not candidates:
        log("  No candidates survived pre-filter")
    else:
        # 8e. Score
        log(f"  Scoring {len(candidates)} candidate(s)...")
        scores       = score_jobs_batch(candidates, resume)
        score_by_url = {s["url"]: s for s in scores}

        for job in candidates:
            s = score_by_url.get(job["url"]) or _unscored(job)

            if not s["scored"]:
                # Scoring failed even after ai_chat's own retries — queue for the next
                # run's rescore_retry_jobs() pass instead of fabricating a score.
                ac     = job.get("applicant_count")
                sal    = job.get("salary_range", "")
                posted = job.get("posted_date")
                src    = job.get("source", "")
                db_add_job({
                    "title":            job["title"],
                    "company":          job["company"],
                    "location":         job["location"],
                    "url":              job["url"],
                    "status":           "Retry",
                    "sponsorship":      "unknown",
                    "scoring_attempts": 1,
                    "description":      job["description"],
                    "applicant_count":  ac,
                    "salary_range":     sal,
                    "posted_date":      posted,
                    "source":           src,
                })
                counters["retry"] += 1
                log(f"  ⏳ [retry]         {job['company']} — {job['title']} (scoring failed)")
                continue

            score        = s["score"]
            sponsorship  = s["sponsorship"]
            company_type = s["company_type"]

            if EXCLUDE_NO_SPONSORSHIP and sponsorship == "no":
                counters["sponsorship"] += 1
                _log_drop(drop_fh, "no-sponsor/AI", job)
                log(f"  ⊘ [no-sponsor/AI]  {job['company']} — {job['title']}")
                continue

            if company_type in SKIP_COMPANY_TYPES:
                counters["staffing_ai"] += 1
                _log_drop(drop_fh, "staffing/AI", job)
                log(f"  ⊘ [STAFFING/AI]    {job['company']} — {job['title']}")
                continue

            if MIN_ATS_SCORE and score < MIN_ATS_SCORE:
                counters["low_score"] += 1
                _log_drop(drop_fh, "low-ats-score", job)
                log(f"  ⊘ [low-ats-score:{score}]  {job['company']} — {job['title']}")
                continue

            ac   = job.get("applicant_count")
            sal  = job.get("salary_range", "")
            posted = job.get("posted_date")
            src  = job.get("source", "")
            db_add_job({
                "title":           job["title"],
                "company":         job["company"],
                "location":        job["location"],
                "url":             job["url"],
                "ats_score":       score,
                "sponsorship":     sponsorship,
                "description":     job["description"],
                "missing_keywords": s["missing_keywords"],
                "applicant_count": ac,
                "salary_range":    sal,
                "posted_date":     posted,
                "source":          src,
            })
            added  += 1
            ac_str  = f"  applicants:{ac}" if ac  is not None else ""
            sal_str = f"  salary:{sal}"     if sal             else ""
            log(f"  ✓ Added [{src}]: {job['company']} — {job['title']} ({job['location']}) ATS:{score}{ac_str}{sal_str}")

    summary = (
        f"\n{'-'*60}\n"
        f"Done. Added {added} new job(s)  |  {ingested} ingested from Notion 'Interested'  |  "
        f"{counters['retry']} queued for retry (scoring failed)\n"
        f"Pre-filter drops -> "
        f"stale:{counters['stale']}  company:{counters['company']}  title:{counters['title']}  "
        f"location:{counters['location']}  no-sponsor:{counters['sponsorship']}  "
        f"staffing/AI:{counters['staffing_ai']}  "
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
