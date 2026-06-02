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

import sys, time, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import *
from scripts.utils import claude_chat, load_resume, db_add_job, db_find_job_by_url, log, today

APIFY_ACTOR = "curious_coder/linkedin-jobs-scraper"
APIFY_BASE  = "https://api.apify.com/v2"


# ── 1. Scrape LinkedIn via Apify ─────────────────────────────

def scrape_jobs(role: str, city: str, max_results: int = 10) -> list[dict]:
    log(f"Scraping LinkedIn for: '{role}' in '{city}'")
    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs"
    payload = {
        "searchUrl": f"https://www.linkedin.com/jobs/search/?keywords={requests.utils.quote(role)}&location={requests.utils.quote(city)}&f_TPR=r86400",
        "maxItems": max_results,
        "proxy": {"useApifyProxy": True},
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


# ── 2. Score job against resume using Claude ─────────────────

def score_job(job: dict, resume: str) -> int:
    prompt = f"""Score how well this job matches the resume on a scale of 0-100 for ATS keyword alignment.

RESUME:
{resume[:3000]}

JOB TITLE: {job.get('title', '')}
COMPANY: {job.get('company', '')}
JOB DESCRIPTION:
{job.get('description', '')[:2000]}

Reply with ONLY a JSON object: {{"score": <number>, "missing_keywords": ["kw1", "kw2"]}}
"""
    try:
        raw = claude_chat(prompt, system="You are an ATS scoring expert. Reply only with valid JSON.")
        import json
        data = json.loads(raw.strip())
        return int(data.get("score", 50)), data.get("missing_keywords", [])
    except Exception:
        return 50, []


# ── 3. Main pipeline ─────────────────────────────────────────

def run():
    resume = load_resume()
    added = 0
    skipped = 0

    for role in TARGET_ROLES:
        try:
            jobs = scrape_jobs(role, TARGET_CITY, max_results=10)
        except Exception as e:
            log(f"  ✗ Scrape failed for '{role}': {e}")
            continue

        log(f"  Found {len(jobs)} listings for '{role}'")

        for job in jobs:
            url = job.get("jobUrl") or job.get("url") or ""
            title = job.get("title") or job.get("positionName") or role
            company = job.get("company") or job.get("companyName") or ""

            if not url:
                continue

            # Skip duplicates
            existing = db_find_job_by_url(url)
            if existing:
                skipped += 1
                continue

            # Score it
            score, missing = score_job({
                "title": title,
                "company": company,
                "description": job.get("description") or job.get("jobDescription") or "",
            }, resume)

            # Add to Supabase (+ Notion mirror if key set)
            db_add_job({
                "title":     title,
                "company":   company,
                "url":       url,
                "ats_score": score,
            })
            added += 1
            log(f"  ✓ Added: {company} — {title} (ATS: {score})")

        time.sleep(2)  # polite pause between role queries

    log(f"\nDone. Added {added} new jobs. Skipped {skipped} duplicates.")
    log(f"View your tracker: https://www.notion.so/{NOTION_DB_ID.replace('-', '')}")


if __name__ == "__main__":
    run()
