#!/usr/bin/env python3
"""
sources.py — Registry of Stage-1 job sources (Step 6, Phase 1)
────────────────────────────────────────────────────────────────
Every source function below returns a list[dict] in the shared output contract:

    {
      "url": str, "title": str, "company": str, "location": str, "description": str,
      "source": str,                 # "linkedin" | "indeed" | "greenhouse" | "lever" | "ashby"
      "posted_date": str | None,     # ISO "YYYY-MM-DD", or None if unknown
      "applicant_count": int | None,
      "salary_range": str,
    }

Two registries, because keyword- and company-scoped sources are shaped differently:
  KEYWORD_SOURCES — fn(role: str) -> list[dict], searched per TARGET_ROLES
  BOARD_SOURCES   — fn(company: str, token: str) -> list[dict], one company's whole board,
                     filtered down to TARGET_ROLES matches by title_matches_targets()

Cross-source dedup (job_fingerprint / collapse_by_fingerprint) and freshness (_is_fresh) also
live here since both operate on this same output contract, upstream of stage1_scrape.py's
company/title/location/sponsorship filters.

TODO (backup plan if Apify sourcing proves unsatisfactory — cost, volume, or actor breakage):
adopt `python-jobspy` (`pip install python-jobspy`) as a free, self-hosted KEYWORD_SOURCES entry.
One `scrape_jobs()` call already covers LinkedIn + Indeed + Glassdoor + Google Jobs + ZipRecruiter
concurrently, and its DataFrame columns map near 1:1 onto this module's output contract (see
docs/refinement-plans/sourcing/scraping-sources.md §B2 for the exact column mapping and the two
caveats — LinkedIn rate-limits without a proxy, and the library's own maintenance cadence is
mixed). Swapping in means adding `"jobspy": scrape_jobspy` to KEYWORD_SOURCES and `"jobspy"` to
ENABLED_SOURCES in config/settings.py; nothing downstream (_pre_filter, collapse_by_fingerprint,
score_jobs_batch, the Notion writer) needs to change, since they all operate on this same dict
shape. See docs/backlog/step-6-multi-source-phase1.md's "Backup plan" section.
"""

import sys, time, re, json, datetime, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import (
    APIFY_API_TOKEN, TARGET_ROLES, MAX_JOB_AGE_DAYS, DROP_UNDATED_JOBS,
)
from scripts.utils import log

ROOT = Path(__file__).parent.parent
APIFY_BASE = "https://api.apify.com/v2"
ATS_TOKENS_PATH = ROOT / "config" / "ats_tokens.json"

# ── Apify actors (LinkedIn + Indeed) ─────────────────────────
# valig~linkedin-jobs-scraper: pay-per-event (~$0.0004/result), no cookie required,
# returns applicationsCount + salary without a Premium session (see Step 1 spike:
# docs/refinement-plans/sourcing/scraping-sources.md). Replaces bebity's $29.99/mo
# rental, whose payload never matched its schema (see git history for the bug).
LINKEDIN_ACTOR = "valig~linkedin-jobs-scraper"
# misceres~indeed-scraper: maintained successor to the deprecated bebity Indeed actor.
INDEED_ACTOR   = "misceres~indeed-scraper"

LINKEDIN_MAX = 25
INDEED_MAX   = 25


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


def _to_iso_date(value) -> str | None:
    """Best-effort conversion of a timestamp (ISO string, epoch seconds/ms, or relative
    phrase) to an ISO "YYYY-MM-DD" date. Returns None if it can't be parsed."""
    if value is None or value == "":
        return None
    # Epoch milliseconds or seconds
    if isinstance(value, (int, float)):
        try:
            secs = value / 1000 if value > 10_000_000_000 else value
            return datetime.datetime.utcfromtimestamp(secs).date().isoformat()
        except (ValueError, OSError, OverflowError):
            return None
    s = str(value).strip()
    if not s:
        return None
    # Numeric string epoch (Lever's createdAt is epoch ms as an int already, but be defensive)
    if s.isdigit():
        return _to_iso_date(int(s))
    # ISO 8601, optionally with a trailing Z or timezone offset
    try:
        s_norm = s.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(s_norm).date().isoformat()
    except ValueError:
        pass
    # Bare "YYYY-MM-DD"
    try:
        return datetime.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


# ── 1a. LinkedIn (valig~linkedin-jobs-scraper) ───────────────

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


def scrape_linkedin(role: str, max_results: int = LINKEDIN_MAX) -> list[dict]:
    """Scrape LinkedIn for `role` posted in the last 24 h."""
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

        posted_raw = job.get("postedAt") or job.get("publishedAt") or job.get("postedDate")

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
            "posted_date":     _to_iso_date(posted_raw),
        })
    log(f"  [LinkedIn] Got {len(results)} listings for '{role}'")
    return results


# ── 1b. Indeed (misceres~indeed-scraper) ─────────────────────

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
        posted_raw = job.get("postingDateParsed") or job.get("date")
        results.append({
            "url":         url,
            "title":       job.get("positionName") or job.get("title") or role,
            "company":     job.get("company") or "",
            "location":    job.get("location") or "",
            "description": job.get("description") or "",
            "source":      "indeed",
            "posted_date": _to_iso_date(posted_raw),
            "applicant_count": None,
            "salary_range":    "",
        })
    log(f"  [Indeed] Got {len(results)} listings for '{role}'")
    return results


# ── 1c. ATS board sources — free, keyless, company-scoped ────

def title_matches_targets(title: str) -> bool:
    """True if `title` contains every token of at least one TARGET_ROLES entry
    (order-independent substring/token match, not exact phrase)."""
    t = (title or "").lower()
    for role in TARGET_ROLES:
        tokens = re.findall(r"[a-z0-9]+", role.lower())
        if tokens and all(tok in t for tok in tokens):
            return True
    return False


def greenhouse_source(company: str, token: str) -> list[dict]:
    """Fetch a company's full Greenhouse board, keep only TARGET_ROLES matches."""
    url = f"https://api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"  ✗ Greenhouse fetch failed for {company} ({token}): {e}")
        return []

    results = []
    for job in data.get("jobs", []) or []:
        title = job.get("title", "")
        if not title_matches_targets(title):
            continue
        # first_published is the true post date; updated_at bumps on any edit and would
        # make a stale req look fresh, so it's only a fallback for missing first_published.
        posted_raw = job.get("first_published") or job.get("updated_at")
        results.append({
            "url":             job.get("absolute_url", ""),
            "title":           title,
            "company":         company,
            "location":        (job.get("location") or {}).get("name", ""),
            "description":     job.get("content", ""),
            "source":          "greenhouse",
            "posted_date":     _to_iso_date(posted_raw),
            "applicant_count": None,
            "salary_range":    "",
        })
    log(f"  [Greenhouse] {company} ({token}): {len(results)} matching listing(s)")
    return results


def lever_source(company: str, token: str) -> list[dict]:
    """Fetch a company's full Lever board, keep only TARGET_ROLES matches."""
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"  ✗ Lever fetch failed for {company} ({token}): {e}")
        return []

    results = []
    for job in data if isinstance(data, list) else []:
        title = job.get("text", "")
        if not title_matches_targets(title):
            continue
        categories = job.get("categories") or {}
        results.append({
            "url":             job.get("hostedUrl") or job.get("applyUrl") or "",
            "title":           title,
            "company":         company,
            "location":        categories.get("location", "") or "",
            "description":     job.get("descriptionPlain") or job.get("description") or "",
            "source":          "lever",
            "posted_date":     _to_iso_date(job.get("createdAt")),
            "applicant_count": None,
            "salary_range":    "",
        })
    log(f"  [Lever] {company} ({token}): {len(results)} matching listing(s)")
    return results


def ashby_source(company: str, token: str) -> list[dict]:
    """Fetch a company's full Ashby board, keep only TARGET_ROLES matches."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"  ✗ Ashby fetch failed for {company} ({token}): {e}")
        return []

    results = []
    for job in data.get("jobs", []) or []:
        title = job.get("title", "")
        if not title_matches_targets(title):
            continue
        comp = job.get("compensation") or {}
        salary = comp.get("compensationTierSummary") or comp.get("summaryComponents") or ""
        results.append({
            "url":             job.get("jobUrl") or job.get("applyUrl") or "",
            "title":           title,
            "company":         company,
            "location":        job.get("location", "") or "",
            "description":     job.get("descriptionPlain") or job.get("descriptionHtml") or "",
            "source":          "ashby",
            "posted_date":     _to_iso_date(job.get("publishedAt")),
            "applicant_count": None,
            "salary_range":    str(salary) if salary else "",
        })
    log(f"  [Ashby] {company} ({token}): {len(results)} matching listing(s)")
    return results


# ── Registries ────────────────────────────────────────────────

KEYWORD_SOURCES = {
    "linkedin": scrape_linkedin,
    "indeed":   scrape_indeed,
}

BOARD_SOURCES = {
    "greenhouse": greenhouse_source,
    "lever":      lever_source,
    "ashby":      ashby_source,
}

# Lower wins on a fingerprint collision — ATS boards are the employer's canonical posting
# (direct-apply URL, full untruncated JD, real date), so collapsing first means the
# sponsorship regex and freshness check run against the fullest JD available.
SOURCE_PRIORITY = {"greenhouse": 0, "lever": 1, "ashby": 2, "linkedin": 3, "indeed": 8}


# ── Cross-source dedup (company + title fingerprint) ─────────

_LEGAL_SUFFIX_TOKENS = {
    "inc", "incorporated", "llc", "corp", "corporation", "ltd", "co", "plc", "the",
}
_ROMAN_TO_ARABIC = {"viii": "8", "vii": "7", "vi": "6", "v": "5", "iv": "4", "iii": "3", "ii": "2", "i": "1"}


def _norm_company(company: str) -> str:
    """Lowercase, strip leading/trailing legal suffixes (inc/llc/ltd/corp/co/the),
    strip non-alphanumerics. "Stripe, Inc." and "Stripe" both normalize to "stripe";
    "Stripe Press" normalizes to "stripepress" and stays distinct."""
    toks = re.findall(r"[a-z0-9]+", (company or "").lower())
    while toks and toks[0] in _LEGAL_SUFFIX_TOKENS:
        toks = toks[1:]
    while toks and toks[-1] in _LEGAL_SUFFIX_TOKENS:
        toks = toks[:-1]
    return "".join(toks)


def _norm_title(title: str) -> str:
    """Lowercase, drop (Remote)/(Hybrid)/(US) parentheticals and trailing dash/location
    clauses, drop req IDs, map roman numerals to arabic. Seniority/level tokens
    ("Senior", "Staff") are deliberately kept — those are different reqs."""
    t = (title or "").lower()
    t = re.split(r"\s[-–—]\s", t, maxsplit=1)[0]        # drop trailing dash/location clause
    t = re.sub(r"\([^)]*\)", " ", t)                     # drop parentheticals
    t = re.sub(r"\breq\.?\s*#?\d+\b", " ", t)             # drop "req 12345" / "req# 12345"
    t = re.sub(r"#\d+\b", " ", t)                         # drop bare "#1234"
    toks = re.findall(r"[a-z0-9]+", t)
    toks = [_ROMAN_TO_ARABIC.get(tok, tok) for tok in toks]
    return " ".join(toks)


def job_fingerprint(company: str, title: str) -> str:
    return f"{_norm_company(company)}|{_norm_title(title)}"


def collapse_by_fingerprint(jobs: list[dict]) -> list[dict]:
    """Collapse jobs sharing a (company, title) fingerprint to a single row, keeping the
    copy from the highest-priority source per SOURCE_PRIORITY (lower number wins)."""
    best: dict[str, dict] = {}
    best_priority: dict[str, int] = {}
    for job in jobs:
        fp = job_fingerprint(job.get("company", ""), job.get("title", ""))
        prio = SOURCE_PRIORITY.get(job.get("source", ""), 5)
        if fp not in best or prio < best_priority[fp]:
            best[fp] = job
            best_priority[fp] = prio
    return list(best.values())


# ── Freshness ─────────────────────────────────────────────────

def _is_fresh(posted_date: str | None) -> bool:
    """None (unknown date) is treated as fresh unless DROP_UNDATED_JOBS is set."""
    if not posted_date:
        return not DROP_UNDATED_JOBS
    try:
        d = datetime.date.fromisoformat(posted_date[:10])
    except ValueError:
        return not DROP_UNDATED_JOBS
    return (datetime.date.today() - d).days <= MAX_JOB_AGE_DAYS


# ── ATS board-token discovery ─────────────────────────────────

def _slugify(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (company or "").lower())


def _load_tokens() -> dict:
    if ATS_TOKENS_PATH.exists():
        try:
            return json.loads(ATS_TOKENS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_tokens(tokens: dict) -> None:
    ATS_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ATS_TOKENS_PATH.write_text(json.dumps(tokens, indent=2, sort_keys=True))


def _probe_greenhouse(company: str, slug: str) -> str | None:
    """Greenhouse is verifiable — reject unless jobs[0].company_name normalized-matches."""
    try:
        r = requests.get(f"https://api.greenhouse.io/v1/boards/{slug}/jobs", timeout=10)
        if r.status_code != 200:
            return None
        jobs = (r.json() or {}).get("jobs", [])
        if not jobs:
            return None
        name = jobs[0].get("company_name") or ""
        if name and _norm_company(name) != _norm_company(company):
            return None
        return slug
    except Exception:
        return None


def _probe_lever(company: str, slug: str) -> str | None:
    """Lever exposes no company field — mitigate with a non-empty board + >=1 TARGET_ROLES
    match, and log every auto-accepted token loudly so the user can pin or veto it."""
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        if not any(title_matches_targets(j.get("text", "")) for j in data):
            return None
        log(f"  ⚠ AUTO-ACCEPTED Lever token '{slug}' for '{company}' — unverifiable "
            f"(no company field on Lever); pin or veto in config/ats_tokens.json")
        return slug
    except Exception:
        return None


def _probe_ashby(company: str, slug: str) -> str | None:
    """Ashby exposes no company field either — same mitigation as Lever."""
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=10)
        if r.status_code != 200:
            return None
        jobs = (r.json() or {}).get("jobs", [])
        if not jobs:
            return None
        if not any(title_matches_targets(j.get("title", "")) for j in jobs):
            return None
        log(f"  ⚠ AUTO-ACCEPTED Ashby token '{slug}' for '{company}' — unverifiable "
            f"(no company field on Ashby); pin or veto in config/ats_tokens.json")
        return slug
    except Exception:
        return None


def discover_tokens(companies: list[str], max_new_probes: int = 20) -> dict:
    """Probe Greenhouse/Lever/Ashby for each company, caching hits AND misses to
    config/ats_tokens.json. Re-probes an all-null entry only if its `checked` date is
    >=30 days old. Caps new-company probes per call at `max_new_probes` and sleeps
    between probes to amortize discovery load."""
    tokens = _load_tokens()
    probed = 0
    for company in companies:
        entry = tokens.get(company)
        if entry:
            all_null = not entry.get("greenhouse") and not entry.get("lever") and not entry.get("ashby")
            if all_null:
                checked = entry.get("checked")
                stale = True
                if checked:
                    try:
                        stale = (datetime.date.today() - datetime.date.fromisoformat(checked)).days >= 30
                    except ValueError:
                        stale = True
                if not stale:
                    continue
            else:
                continue  # already have at least one hit — no need to re-probe

        if probed >= max_new_probes:
            continue

        slug = _slugify(company)
        gh = _probe_greenhouse(company, slug)
        time.sleep(0.4)
        lv = _probe_lever(company, slug)
        time.sleep(0.4)
        ab = _probe_ashby(company, slug)

        tokens[company] = {
            "greenhouse": gh, "lever": lv, "ashby": ab,
            "checked": datetime.date.today().isoformat(),
        }
        probed += 1

    _save_tokens(tokens)
    return tokens
