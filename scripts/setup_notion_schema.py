#!/usr/bin/env python3
"""
setup_notion_schema.py — one-time: add Stage 7's Notion properties + Status options.

WHY THIS EXISTS
    Two different Notion endpoints behave differently, and conflating them is the trap:
      · pages.update  — writing a Status the select doesn't offer is SILENTLY IGNORED. The page
                        updates, the API returns 200, the status just doesn't change. This is
                        why scripts/autoapply.py writes status via db_update_status_verified().
      · databases.update — CAN add select options and properties to the schema itself.
    So the schema genuinely is scriptable; only the per-page write isn't. This script does the
    schema half once, so stage 7 has somewhere to write.

WHAT IT ADDS (idempotent — anything already present is left exactly as-is)
    Status select options : Application Queued, Applying, Needs Human: Captcha,
                            Needs Human: Auth, Needs Human: Question, Apply Failed
    Properties            : Apply Channel (select), Apply Attempts (number),
                            Needs Human Reason (rich_text), Application Log (rich_text)

SAFETY
    Dry-run by default: prints exactly what it would change and exits without writing. Pass
    --apply to actually patch. Existing Status options are resent with their original ids so
    none are dropped, and no existing property is ever modified or removed.

Run:
    python scripts/setup_notion_schema.py            # dry run — show the plan
    python scripts/setup_notion_schema.py --apply    # actually patch the database
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import NOTION_API_KEY, NOTION_DB_ID
from scripts.utils import log

# Kept in sync with scripts/autoapply.py's STATUS_* constants. "Applying" is included for the
# spec's transition diagram even though this phase never writes it — adding it now costs
# nothing and avoids a second manual pass if Phase 3 lands.
REQUIRED_STATUS_OPTIONS = [
    "Application Queued",
    "Applying",
    "Needs Human: Captcha",
    "Needs Human: Auth",
    "Needs Human: Question",
    "Apply Failed",
]

# Mirrors the keys in utils._EXTRA_TO_NOTION that stage 7 writes. Without these columns those
# values are silently dropped (each converter only runs when the caller supplies the key), so
# the stage would "work" while recording nothing.
REQUIRED_PROPERTIES = {
    "Apply Channel": {
        "select": {"options": [{"name": n} for n in
                               ("greenhouse", "lever", "ashby", "workday",
                                "linkedin", "indeed", "unknown")]}
    },
    "Apply Attempts":      {"number": {"format": "number"}},
    "Needs Human Reason":  {"rich_text": {}},
    "Application Log":     {"rich_text": {}},
}


def missing_status_options(schema: dict) -> list[str]:
    """Which REQUIRED_STATUS_OPTIONS the Status select doesn't already offer."""
    status = (schema.get("properties") or {}).get("Status") or {}
    existing = {o.get("name") for o in (status.get("select") or {}).get("options", [])}
    return [name for name in REQUIRED_STATUS_OPTIONS if name not in existing]


def missing_properties(schema: dict) -> list[str]:
    """Which REQUIRED_PROPERTIES the database doesn't already have."""
    existing = set((schema.get("properties") or {}).keys())
    return [name for name in REQUIRED_PROPERTIES if name not in existing]


def build_patch(schema: dict) -> dict:
    """Build the databases.update `properties` payload. Returns {} when nothing is missing.

    Existing Status options are resent verbatim (ids intact) with the new ones appended —
    sending only the new options would drop every option already there, taking the pipeline's
    entire status vocabulary with it.
    """
    patch: dict = {}

    new_options = missing_status_options(schema)
    if new_options:
        status = (schema.get("properties") or {}).get("Status") or {}
        existing = list((status.get("select") or {}).get("options", []))
        patch["Status"] = {"select": {"options": existing + [{"name": n} for n in new_options]}}

    for name in missing_properties(schema):
        patch[name] = REQUIRED_PROPERTIES[name]

    return patch


def _client():
    from notion_client import Client
    return Client(auth=NOTION_API_KEY)


def run(apply: bool = False) -> int:
    if not NOTION_API_KEY:
        log("✗ NOTION_API_KEY is not set. Add it to your .env and re-run.")
        return 1
    if not NOTION_DB_ID:
        log("✗ NOTION_DB_ID is not set in config/settings.py.")
        return 1

    notion = _client()
    try:
        schema = notion.databases.retrieve(database_id=NOTION_DB_ID)
    except Exception as e:
        log(f"✗ Could not read the database ({e}).")
        log("  Check NOTION_API_KEY, and that the integration is shared with the tracker DB.")
        return 1

    title = "".join(t.get("plain_text", "") for t in schema.get("title", [])) or NOTION_DB_ID
    log(f"Database: {title}")

    new_options = missing_status_options(schema)
    new_props = missing_properties(schema)

    if not new_options and not new_props:
        log("✓ Nothing to do — every Stage 7 property and Status option already exists.")
        return 0

    log("\nPlanned changes:")
    for name in new_options:
        log(f"  + Status option   : {name}")
    for name in new_props:
        kind = next(iter(REQUIRED_PROPERTIES[name]))
        log(f"  + Property        : {name}  ({kind})")

    if not apply:
        log("\nDry run — nothing was written. Re-run with --apply to make these changes.")
        return 0

    patch = build_patch(schema)
    try:
        notion.databases.update(database_id=NOTION_DB_ID, properties=patch)
    except Exception as e:
        log(f"\n✗ Update failed ({e}). Nothing partial should have been applied; re-run to retry.")
        return 1

    # Read back rather than trusting the 200 — the whole reason this script exists is that
    # Notion can accept a write and not apply it.
    try:
        after = notion.databases.retrieve(database_id=NOTION_DB_ID)
    except Exception as e:
        log(f"\n⚠ Patch sent, but the readback failed ({e}). Re-run to confirm.")
        return 1

    still_missing = missing_status_options(after) + missing_properties(after)
    if still_missing:
        log(f"\n✗ Still missing after the update: {', '.join(still_missing)}")
        log("  Add these by hand in Notion, or check the integration has edit access.")
        return 1

    log(f"\n✓ Applied. {len(new_options)} status option(s) and {len(new_props)} property(ies) added.")
    log("  Stage 7 can now transition jobs: python run.py --stage 7")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="One-time: add Stage 7's Notion properties and Status options.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually patch the database (default is a dry run).")
    return run(apply=ap.parse_args(argv).apply)


if __name__ == "__main__":
    raise SystemExit(main())
