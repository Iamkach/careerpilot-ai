#!/usr/bin/env python3
"""
Step 13 Phase 1 verification spike — NOT part of the pipeline.

Calls the LinkedIn and Indeed Apify actors once each (small max_results, one role)
and reports which apply-URL field is actually populated, so we know before writing
1a/1b/1c whether the harvest premise holds. See docs/backlog/step-13-board-token-harvesting.md,
"Unverified assumption — check first."

Costs real Apify credits. Run manually: python scripts/spike_step13_apply_url_fields.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.sources import _apify_run, LINKEDIN_ACTOR, INDEED_ACTOR, _linkedin_payload_base

ROLE = "Software Engineer"
N = 10  # keep the spike cheap

LINKEDIN_URL_FIELDS = ["jobUrl", "link", "url", "applyUrl", "externalApplyLink", "companyApplyUrl"]
INDEED_URL_FIELDS   = ["url", "jobUrl", "externalApplyLink", "applyUrl", "companyApplyUrl"]


def field_report(items: list[dict], fields: list[str], label: str):
    print(f"\n=== {label}: {len(items)} items ===")
    if items:
        print("Sample keys of item[0]:", sorted(items[0].keys()))
    counts = {f: 0 for f in fields}
    for it in items:
        for f in fields:
            if it.get(f):
                counts[f] += 1
    for f, c in counts.items():
        print(f"  {f:22s} populated in {c}/{len(items)}")
    # print a couple of raw examples of the non-canonical fields (candidates for apply_url)
    for f in fields:
        for it in items:
            if it.get(f):
                print(f"  example {f}: {it[f]!r}")
                break


def main():
    import os
    li_items = []
    if not os.environ.get("SKIP_LINKEDIN"):
        print(f"--- LinkedIn actor: {LINKEDIN_ACTOR} ---")
        li_payload = _linkedin_payload_base(ROLE, N)
        try:
            li_items = _apify_run(LINKEDIN_ACTOR, li_payload)
        except Exception as e:
            print(f"LinkedIn run failed: {e}")
            li_items = []
        field_report(li_items, LINKEDIN_URL_FIELDS, "LinkedIn")
    else:
        print("--- LinkedIn: skipped (already spiked, applyUrl confirmed empty) ---")

    print(f"\n--- Indeed actor: {INDEED_ACTOR} (followApplyRedirects=False) ---")
    in_payload = {
        "position": ROLE,
        "country": "US",
        "location": "",
        "maxItemsPerSearch": N,
        "parseCompanyDetails": False,
        "saveOnlyUniqueItems": True,
        "followApplyRedirects": False,
    }
    import time as _time
    t0 = _time.monotonic()
    try:
        in_items = _apify_run(INDEED_ACTOR, in_payload)
    except Exception as e:
        print(f"Indeed run failed: {e}")
        in_items = []
    t_no_redirect = _time.monotonic() - t0
    field_report(in_items, INDEED_URL_FIELDS, "Indeed (no redirect)")
    print(f"  wall time: {t_no_redirect:.1f}s")

    print(f"\n--- Indeed actor: {INDEED_ACTOR} (followApplyRedirects=True) ---")
    in_payload_redirect = {**in_payload, "followApplyRedirects": True}
    t0 = _time.monotonic()
    try:
        in_items_redirect = _apify_run(INDEED_ACTOR, in_payload_redirect)
    except Exception as e:
        print(f"Indeed (redirect) run failed: {e}")
        in_items_redirect = []
    t_redirect = _time.monotonic() - t0
    field_report(in_items_redirect, INDEED_URL_FIELDS, "Indeed (redirect)")
    print(f"  wall time: {t_redirect:.1f}s (vs {t_no_redirect:.1f}s without redirect)")
    in_items = in_items_redirect  # dump the redirect-following version

    out = Path(__file__).parent.parent / "output" / "spike_step13_raw_items.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"linkedin": li_items, "indeed": in_items}, indent=2))
    print(f"\nRaw items dumped to {out}")


if __name__ == "__main__":
    main()
