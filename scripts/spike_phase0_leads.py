#!/usr/bin/env python3
"""
spike_phase0_leads.py — THROWAWAY Phase 0 spike for the communications subsystem
──────────────────────────────────────────────────────────────────────────────
Not a pipeline stage. Not wired into run.py. Delete this file once its answers are
transcribed into docs/backlog/step-7-communications-subsystem.md's Phase 0 checklist.

Settles four real unknowns with LIVE API calls before any Phase 1+ code
(scripts/credits.py, stage7_leads_discover.py, stage8_email_resolve.py, the Leads DB, ...)
gets written — coding those around a guess would violate the subsystem's own governing rule
("APIs supply facts; never guess one"). See docs/refinement-plans/communications/
communications-subsystem.md, "Phase 0 — Blocking spike" for full context.

  Q1. Does Hunter's Email Finder return a terminal `verification.status` inline, or
      pending/null? Decides whether the Verifier (0.5 credit) is ever needed.
  Q2. Does the free tier honor Email Finder's `linkedin_handle` param? If yes, a coregent
      profile URL feeds Hunter directly and domain resolution is skipped entirely.
  Q3. Billing edges: not-found = 0 credits; what does an accept_all hit actually cost?
  Q4. Is Clearbit's keyless autocomplete still up? What does coregent's raw dataset look
      like against 1-2 real Notion jobs (field names, shapes) — never assume the vendor docs.

Run:  python scripts/spike_phase0_leads.py
Requires: HUNTER_API_KEY set in your env (or config/settings.py). APIFY_API_TOKEN is
already configured. Fails loudly (not a stack trace) if HUNTER_API_KEY is missing.
"""

import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from config.settings import HUNTER_API_KEY, LEAD_ACTOR
from scripts.utils import db_get_jobs, db_get_all_jobs, log
from scripts.sources import _apify_run

HUNTER_BASE = "https://api.hunter.io/v2"


def _fail(msg: str) -> None:
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def _hunter_get(path: str, **params) -> dict:
    params["api_key"] = HUNTER_API_KEY
    r = requests.get(f"{HUNTER_BASE}/{path}", params=params)
    print(f"\n--- GET {path} params={ {k: v for k, v in params.items() if k != 'api_key'} } ---")
    print(f"status: {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        body = {"raw_text": r.text}
    print(json.dumps(body, indent=2)[:4000])
    return body


def pick_sample_jobs() -> list[dict]:
    jobs = db_get_jobs("Reviewed")
    if not jobs:
        log("[spike] no 'Reviewed' jobs found, falling back to db_get_all_jobs()")
        jobs = db_get_all_jobs()
    if not jobs:
        _fail("No jobs found in Notion at all — add at least one job before running this spike.")
    return jobs[:2]


def spike_coregent(jobs: list[dict]) -> list[dict]:
    """Q4 (part 1): call the real actor against real jobs, print the RAW dataset unmodified."""
    print("\n" + "=" * 70)
    print("Q4a — coregent raw field map")
    print("=" * 70)
    urls = [j["url"] for j in jobs if j.get("url")]
    if not urls:
        print("  (no job URLs available — skipping coregent call)")
        return []
    payload = {"urls": urls, "maxResults": 3}
    try:
        items = _apify_run(LEAD_ACTOR, payload)
    except Exception as e:
        print(f"  [FAIL] coregent call failed: {e}")
        return []
    print(f"  {len(items)} raw item(s) returned. Full dataset:")
    print(json.dumps(items, indent=2)[:6000])
    return items


def spike_clearbit(jobs: list[dict]) -> None:
    """Q4 (part 2): is Clearbit's keyless autocomplete still up?"""
    print("\n" + "=" * 70)
    print("Q4b — Clearbit keyless autocomplete liveness")
    print("=" * 70)
    companies = list({j["company"] for j in jobs if j.get("company")})[:2]
    for company in companies:
        r = requests.get(
            "https://autocomplete.clearbit.com/v1/companies/suggest",
            params={"query": company},
        )
        print(f"\n--- GET clearbit suggest?query={company!r} ---")
        print(f"status: {r.status_code}")
        print(r.text[:2000])


def spike_hunter_account(label: str) -> dict:
    return _hunter_get("account")


def spike_hunter_email_finder(jobs: list[dict], coregent_items: list[dict]) -> None:
    """Q1 (verification timing) and Q2 (linkedin_handle support)."""
    print("\n" + "=" * 70)
    print("Q1 — Email Finder verification.status: terminal or pending/null?")
    print("=" * 70)
    company = jobs[0]["company"] if jobs else "example.com"
    # A real domain is needed — use the job's own URL host as a best-effort guess, or let
    # the user supply one. This is a spike, not production domain resolution.
    before = spike_hunter_account("before finder call")
    _hunter_get("email-finder", company=company, first_name="Jane", last_name="Doe")

    print("\n" + "=" * 70)
    print("Q2 — does the free tier honor linkedin_handle?")
    print("=" * 70)
    li_handle = None
    for item in coregent_items:
        li = item.get("linkedin_profile_url") or item.get("linkedinUrl") or item.get("linkedin")
        if li:
            li_handle = li
            break
    if li_handle:
        _hunter_get("email-finder", linkedin_handle=li_handle)
    else:
        print("  (no coregent lead had a LinkedIn profile URL — skipping)")

    print("\n" + "=" * 70)
    print("Q3 — billing edges: not-found = 0 credits?")
    print("=" * 70)
    _hunter_get("email-finder", company=company, first_name="Zzqxnonexistent", last_name="Nobody")
    after = spike_hunter_account("after calls")

    try:
        used_before = before["data"]["requests"]["searches"]["used"]
        used_after = after["data"]["requests"]["searches"]["used"]
        print(f"\n  searches.used before={used_before} after={used_after} delta={used_after - used_before}")
    except (KeyError, TypeError):
        print("\n  (could not diff searches.used — inspect the raw /account responses above)")


def print_summary() -> None:
    print("\n" + "=" * 70)
    print("SPIKE SUMMARY — transcribe these into docs/backlog/step-7-communications-subsystem.md")
    print("=" * 70)
    print("""
  Q1. Was verification.status terminal (valid/invalid/accept_all/webmail/disposable) on
      every Email Finder response above, or did any come back pending/null?
      -> If terminal: Verifier is never needed, capacity stays ~50/month.
      -> If pending/null: call Verifier (0.5 cr) only for those, re-apply the email policy table.

  Q2. Did the linkedin_handle call return a match, or was it ignored/rejected on the free tier?
      -> If honored: skip domain resolution whenever a LinkedIn profile URL exists.

  Q3. Did the not-found query cost any searches.used delta? What would an accept_all hit cost?
      -> Confirms "not-found = 0 credits" before coding the budget guard in scripts/credits.py.

  Q4. What are coregent's ACTUAL field names for: profile URL, name, title, seniority,
      department, is_recruiter_like, is_direct_job_poster, relevance_score?
      Is Clearbit's autocomplete endpoint still live (200) or dead (404/other)?
      -> Write the field map against this real output, never the vendor docs.
""")


def main() -> None:
    if not HUNTER_API_KEY:
        _fail(
            "HUNTER_API_KEY is not set. Set it in your environment "
            "(e.g. `export HUNTER_API_KEY=...`) or config/settings.py before running this spike."
        )

    jobs = pick_sample_jobs()
    print(f"[spike] testing against {len(jobs)} real job(s): "
          f"{[(j['company'], j['title']) for j in jobs]}")

    coregent_items = spike_coregent(jobs)
    spike_clearbit(jobs)
    spike_hunter_email_finder(jobs, coregent_items)
    print_summary()


if __name__ == "__main__":
    main()
