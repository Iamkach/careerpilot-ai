#!/usr/bin/env python3
"""
provision_notion.py — create a fork's Notion workspace from scratch.

WHY THIS EXISTS
    The pipeline is Notion-first: every stage reads/writes a "Job Search Tracker" database, the
    optional mobile intake reads a "Job Link Scratch Pad" database, the optional
    restricted-sponsorship company filter reads a "Restricted Sponsorship Companies" database,
    and the optional curated target-companies + ATS-token store reads a "Target Companies"
    database. The author's databases already exist; a *fork* has nothing.
    `setup_notion_schema.py` can only *patch* an existing DB (databases.update) — it cannot
    create one. This module does the create half:

        parent page you shared with your integration
          └── "Careerpilot-ai"                        (a page we create under it)
                ├── "Job Search Tracker"                (databases.create — full schema, all Status options)
                ├── "Job Link Scratch Pad"               (databases.create — a single URL/title column)
                ├── "Restricted Sponsorship Companies"   (databases.create — a single company-name/title column)
                └── "Target Companies"                   (databases.create — company name + Greenhouse/Lever/Ashby/Last Checked)

    Defining every Status select option at *create* time sidesteps the API quirk that
    `pages.update` silently ignores a Status the select doesn't already offer — `databases.create`
    has no such limit. This mirrors the reorganized live workspace (one parent page, four DBs).

SINGLE SOURCE OF TRUTH
    STATUS_OPTIONS / TRACKER_PROPERTIES here are the canonical tracker schema. setup_notion_schema
    imports the Stage-7 subset (STAGE7_STATUS_OPTIONS / _stage7_properties()) from this module so
    the "create" and "patch" paths can never drift.

Run (file-fallback path — the wizard `python run.py --init` calls provision() for you):
    python scripts/provision_notion.py --parent-page <shared_page_id>
"""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import NOTION_API_KEY
from scripts.utils import log


# ── Canonical tracker schema (authority: the live "Job Search Tracker" data source) ──

# The full Status vocabulary, in one place. The first 14 are the pipeline + manual-only states;
# "Needs Review" and the six Stage-7 states follow. setup_notion_schema patches only the Stage-7
# subset onto an existing DB; here they are all defined up front on a fresh one.
STATUS_OPTIONS = [
    "Interested", "Scraped", "Reviewed", "Resume Tailored", "Applied", "Outreach Sent",
    "Interview Scheduled", "Offer Received", "Retry", "Disregard", "Blacklist", "Archived",
    "Rejected", "Human Review", "Needs Review",
    # Stage 7 (auto-apply)
    "Application Queued", "Applying", "Needs Human: Captcha", "Needs Human: Auth",
    "Needs Human: Question", "Apply Failed",
]

# The Stage-7 additions setup_notion_schema.py is responsible for patching onto an existing DB.
STAGE7_STATUS_OPTIONS = [
    "Application Queued", "Applying", "Needs Human: Captcha", "Needs Human: Auth",
    "Needs Human: Question", "Apply Failed",
]
STAGE7_PROPERTY_NAMES = ["Apply Channel", "Apply Attempts", "Needs Human Reason", "Application Log"]

APPLY_CHANNEL_OPTIONS = ["greenhouse", "lever", "ashby", "workday", "linkedin", "indeed", "unknown"]
SPONSORSHIP_OPTIONS = ["yes", "no", "unknown"]


def _select(names: list[str]) -> dict:
    return {"select": {"options": [{"name": n} for n in names]}}


# databases.create-shaped property specs for the whole tracker. Names/types mirror the live DB,
# plus `Enrichment Attempts` (number) — documented in CLAUDE.md and written optionally by the
# "Interested" intake, but missing from the author's own DB; a fresh DB should carry it.
TRACKER_PROPERTIES: dict = {
    "Job Title":               {"title": {}},
    "Company":                 {"rich_text": {}},
    "Location":                {"rich_text": {}},
    "Job URL":                 {"url": {}},
    "Status":                  _select(STATUS_OPTIONS),
    "Sponsorship":             _select(SPONSORSHIP_OPTIONS),
    "Date Scraped":            {"date": {}},
    "Posted Date":             {"date": {}},
    "Date Applied":            {"date": {}},
    "ATS Match Score":         {"number": {"format": "number"}},
    "Applicant Count":         {"number": {"format": "number"}},
    "Scoring Attempts":        {"number": {"format": "number"}},
    "Enrichment Attempts":     {"number": {"format": "number"}},
    "Tailored Resume Link":    {"url": {}},
    "Hiring Manager":          {"rich_text": {}},
    "Hiring Manager LinkedIn": {"url": {}},
    "Notes":                   {"rich_text": {}},
    "Referral Contact":        {"rich_text": {}},
    "Source":                  {"rich_text": {}},
    "Salary Range":            {"rich_text": {}},
    "Missing Keywords":        {"rich_text": {}},
    # Stage 7 (auto-apply) columns
    "Apply Channel":           _select(APPLY_CHANNEL_OPTIONS),
    "Apply Attempts":          {"number": {"format": "number"}},
    "Needs Human Reason":      {"rich_text": {}},
    "Application Log":         {"rich_text": {}},
    # Auto-incrementing id — nice-to-have; no stage reads/writes it, so it's added defensively.
    "Job ID":                  {"unique_id": {}},
}

# The scratch pad only needs one title column holding a job URL. get_scratch_note_entries() reads
# whichever property is the title, so the name is cosmetic — do NOT replicate Notion's default
# "Question 1/Question 2/Respondent" template columns the live pad still carries.
SCRATCH_PROPERTIES: dict = {"Job URL": {"title": {}}}

# Same one-column shape as the scratch pad, holding a restricted company name instead of a URL.
# get_restricted_companies_from_notion() reads whichever property is the title, so the name is
# cosmetic here too.
RESTRICTED_COMPANIES_PROPERTIES: dict = {"Company": {"title": {}}}

# Curated target-companies list + persistent ATS-token store (Step 14). "Company" is the title;
# the three ATS columns hold the discovered board token (blank = not found there), and
# "Last Checked" backs discover_tokens()'s 30-day re-probe-if-stale check the same way the
# local config/ats_tokens.json cache's "checked" field does.
TARGET_COMPANIES_PROPERTIES: dict = {
    "Company":      {"title": {}},
    "Greenhouse":   {"rich_text": {}},
    "Lever":        {"rich_text": {}},
    "Ashby":        {"rich_text": {}},
    "Last Checked": {"date": {}},
}


def _stage7_properties() -> dict:
    """The Stage-7 property specs, sliced from the canonical tracker schema (no drift)."""
    return {name: TRACKER_PROPERTIES[name] for name in STAGE7_PROPERTY_NAMES}


# ── Validation (reused by run.py --setup) ────────────────────────────────────

def missing_from_schema(schema: dict) -> list[str]:
    """Return human-readable names of tracker properties / Status options the DB is missing.

    `schema` is a databases.retrieve() response. Used to turn `--setup`'s presence-only Notion
    check into a real schema check.
    """
    props = schema.get("properties") or {}
    missing = [f"property: {name}" for name in TRACKER_PROPERTIES if name not in props]

    status = props.get("Status") or {}
    have = {o.get("name") for o in (status.get("select") or {}).get("options", [])}
    missing += [f"status: {name}" for name in STATUS_OPTIONS if name not in have]
    return missing


def validate_schema(db_id: str, notion=None) -> list[str]:
    """Retrieve `db_id` and return the list of missing properties/status options ([] == healthy).

    Raises on a failed read — an unreadable DB is not the same as a complete one, and the caller
    must be able to tell the difference.
    """
    notion = notion or _client()
    schema = notion.databases.retrieve(database_id=db_id)
    return missing_from_schema(schema)


# ── Page-id / share-link parsing ─────────────────────────────────────────────

# A Notion id is 32 hex chars, dashed (8-4-4-4-12) or not. In a share link it trails the title
# slug, e.g. .../Careerpilot-ai-3a50a7a3e7198071b70bdef6519fb1a5 or /p/3a50a7a3-e719-…?pvs=1.
_PAGE_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"
)


def normalize_page_id(raw: str) -> str:
    """Accept a Notion page id OR a share link/URL and return a dashed UUID.

    The id always trails the (possibly dash-separated) title slug, so we take the *last* 32-hex
    run after dropping any query/fragment. Raises ValueError if none is found — a wrong page here
    means provisioning writes into the wrong place, so guessing is worse than asking again.
    """
    cleaned = (raw or "").strip().split("?")[0].split("#")[0]
    matches = _PAGE_ID_RE.findall(cleaned)
    if not matches:
        raise ValueError(
            f"Couldn't find a Notion page id in {raw!r}. Paste the page's 'Copy link' URL "
            "(or its 32-character id)."
        )
    h = matches[-1].replace("-", "").lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ── Provisioning ─────────────────────────────────────────────────────────────

def _client():
    """The shared, cached notion_client (raises if NOTION_API_KEY is unset)."""
    from scripts.utils import _notion
    return _notion()


def _create_database(notion, page_id: str, title: str, properties: dict) -> str:
    """databases.create under `page_id`; tolerate an API that rejects the unique_id type.

    `unique_id` is a newer property type; if the pinned notion-client / API version rejects it,
    retry without `Job ID` (no stage depends on it) rather than failing the whole provision.
    """
    try:
        db = notion.databases.create(
            parent={"type": "page_id", "page_id": page_id},
            title=[{"type": "text", "text": {"content": title}}],
            properties=properties,
        )
    except Exception as e:
        if "Job ID" in properties:
            log(f"  ⚠ '{title}': Job ID (unique_id) rejected by the API ({e}); creating without it.")
            trimmed = {k: v for k, v in properties.items() if k != "Job ID"}
            db = notion.databases.create(
                parent={"type": "page_id", "page_id": page_id},
                title=[{"type": "text", "text": {"content": title}}],
                properties=trimmed,
            )
        else:
            raise
    return db["id"]


def provision(parent_page_id: str, notion=None) -> tuple[str, str, str, str]:
    """Create the 'Careerpilot-ai' page + all four databases under `parent_page_id`.

    `parent_page_id` is a page the forker has shared with their integration — either a raw id or
    a full Notion share link (a "Copy link" URL), which is normalized here. Returns
    (tracker_db_id, scratch_db_id, restricted_companies_db_id, target_companies_db_id). All new
    DBs inherit access from that shared parent.
    """
    notion = notion or _client()
    parent_page_id = normalize_page_id(parent_page_id)

    log("Creating the 'Careerpilot-ai' container page…")
    page = notion.pages.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        properties={"title": [{"type": "text", "text": {"content": "Careerpilot-ai"}}]},
    )
    page_id = page["id"]

    log("Creating the 'Job Search Tracker' database…")
    tracker_id = _create_database(notion, page_id, "Job Search Tracker", TRACKER_PROPERTIES)

    log("Creating the 'Job Link Scratch Pad' database…")
    scratch_id = _create_database(notion, page_id, "Job Link Scratch Pad", SCRATCH_PROPERTIES)

    log("Creating the 'Restricted Sponsorship Companies' database…")
    restricted_id = _create_database(
        notion, page_id, "Restricted Sponsorship Companies", RESTRICTED_COMPANIES_PROPERTIES
    )

    log("Creating the 'Target Companies' database…")
    target_companies_id = _create_database(
        notion, page_id, "Target Companies", TARGET_COMPANIES_PROPERTIES
    )

    log(f"✓ Provisioned. Tracker DB: {tracker_id}  |  Scratch DB: {scratch_id}  |  "
        f"Restricted Companies DB: {restricted_id}  |  Target Companies DB: {target_companies_id}")
    return tracker_id, scratch_id, restricted_id, target_companies_id


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Create the Careerpilot-ai Notion page + Job Search Tracker + Job Link "
                    "Scratch Pad + Restricted Sponsorship Companies + Target Companies "
                    "databases under a page you've shared with your integration.")
    ap.add_argument("--parent-page", required=True, dest="parent_page",
                    help="Notion page share link (or raw id) you've shared with your integration; "
                         "the new 'Careerpilot-ai' page + databases are created under it.")
    args = ap.parse_args(argv)

    if not NOTION_API_KEY:
        log("✗ NOTION_API_KEY is not set. Add it to your .env and re-run.")
        return 1
    try:
        tracker_id, scratch_id, restricted_id, target_companies_id = provision(args.parent_page)
    except Exception as e:
        log(f"✗ Provisioning failed ({e}).")
        log("  Check NOTION_API_KEY and that the parent page is shared with the integration.")
        return 1

    log("\nAdd these to your .env (or let `python run.py --init` do it):")
    log(f"  NOTION_DB_ID={tracker_id}")
    log(f"  NOTION_SCRATCH_PAGE_ID={scratch_id}")
    log(f"  NOTION_RESTRICTED_COMPANIES_PAGE_ID={restricted_id}")
    log(f"  NOTION_TARGET_COMPANIES_PAGE_ID={target_companies_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
