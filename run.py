#!/usr/bin/env python3
"""
run.py — Master pipeline runner
────────────────────────────────
Two-step daily flow:

  Step 1 — Scrape & review (run each morning):
    python run.py                          # Scrape + score → review digest email → STOP
                                           # Open Notion, set Status=Disregard on bad jobs

  Step 2 — Tailor reviewed jobs:
    python run.py --evaluate               # Sync Disregard → tailor + outreach + ready digest

  Individual stages:
    python run.py --stage 1               # Scrape only
    python run.py --stage 2 --min-score 65
    python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
    python run.py --stage 4 --send
    python run.py --stage 5 --company "Google" --role "Senior PM"
    python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000
    python run.py --setup                  # Check config & install deps
"""

import sys, argparse, subprocess
from pathlib import Path

# Windows terminals default to cp1252; force UTF-8 so emoji/check marks render
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent


# ── Dependency check ──────────────────────────────────────────

# Only the active provider's SDK is required; the others are optional
_PROVIDER_PKGS = {"claude": "anthropic", "gemini": "google-generativeai", "codex": "openai"}

def _get_required():
    from config.settings import AI_PROVIDER
    provider_pkg = _PROVIDER_PKGS.get(AI_PROVIDER, "anthropic")
    return [provider_pkg, "supabase", "notion_client", "requests"]

def check_setup():
    print("=== Setup Check ===\n")
    from config.settings import (
        AI_PROVIDER, AI_MODEL_OVERRIDE,
        ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY,
        APIFY_API_TOKEN, NOTION_API_KEY, NOTION_DB_ID,
        SUPABASE_URL, SUPABASE_KEY, RESUME_PATH
    )

    _provider_key = {
        "claude": ("Anthropic API key", ANTHROPIC_API_KEY, "Set ANTHROPIC_API_KEY in config/settings.py"),
        "gemini": ("Gemini API key",    GEMINI_API_KEY,    "Set GEMINI_API_KEY in config/settings.py"),
        "codex":  ("OpenAI API key",    OPENAI_API_KEY,    "Set OPENAI_API_KEY in config/settings.py"),
    }
    _defaults = {"claude": "claude-opus-4-6", "gemini": "gemini-2.0-flash", "codex": "gpt-4o"}
    active_model = AI_MODEL_OVERRIDE or _defaults.get(AI_PROVIDER, "?")
    print(f"  AI provider : {AI_PROVIDER}  (model: {active_model})\n")

    key_label, key_val, key_fix = _provider_key.get(
        AI_PROVIDER,
        ("Unknown provider key", False, f"Set AI_PROVIDER to claude/gemini/codex in config/settings.py")
    )

    checks = [
        (key_label,    bool(key_val),              key_fix),
        ("Apify token",     bool(APIFY_API_TOKEN), "Set APIFY_API_TOKEN in config/settings.py"),
        ("Supabase URL",    bool(SUPABASE_URL),    "Set SUPABASE_URL in config/settings.py"),
        ("Supabase key",    bool(SUPABASE_KEY),    "Set SUPABASE_KEY in config/settings.py"),
        ("Notion API key",  bool(NOTION_API_KEY),  "Set NOTION_API_KEY in config/settings.py (optional — visual tracker)"),
        ("Notion DB ID",    bool(NOTION_DB_ID),    "Already set — your tracker DB"),
        ("Resume file",     (ROOT / RESUME_PATH).exists(), f"Add your resume to {RESUME_PATH}"),
    ]

    all_ok = True
    for label, ok, fix in checks:
        status = "✓" if ok else "✗"
        print(f"  {status} {label}")
        if not ok:
            print(f"    → {fix}")
            all_ok = False

    print()
    missing = []
    for pkg in _get_required():
        import_name = pkg.replace("-", "_").replace("google_generativeai", "google.generativeai")
        try:
            __import__(import_name)
            print(f"  ✓ {pkg}")
        except ImportError:
            print(f"  ✗ {pkg} not installed")
            missing.append(pkg)

    if missing:
        print(f"\nInstall missing packages:")
        print(f"  pip install {' '.join(missing)}")

    if all_ok and not missing:
        print("\n✅ All good — you're ready to run!")
    else:
        print("\n⚠  Fix the above before running.")


# ── Stage runners ─────────────────────────────────────────────

def stage1(args):
    print("\n🔍 STAGE 1 — Scrape fresh LinkedIn jobs")
    print("─" * 45)
    from scripts.stage1_scrape import run
    run()

def stage2(args):
    print("\n✍️  STAGE 2 — Tailor resumes")
    print("─" * 45)
    from scripts.stage2_tailor import run
    run(min_score=args.min_score)

def stage3(args):
    print("\n📧 STAGE 3 — Draft outreach emails")
    print("─" * 45)
    from scripts.stage3_outreach import run
    run(target_company=args.company, contact=args.contact, contact_role=args.contact_role)

def stage4(args, mode: str = "ready"):
    print("\n📋 STAGE 4 — Morning digest")
    print("─" * 45)
    from scripts.stage4_digest import run
    run(send=args.send, mode=mode)

def stage5(args):
    print("\n🎯 STAGE 5 — Interview prep guide")
    print("─" * 45)
    from scripts.stage5_interview_prep import run
    run(company=args.company, role=args.role, jd_file=args.jd_file, hm_linkedin=args.hm_linkedin)

def stage6(args):
    print("\n💰 STAGE 6 — Salary negotiation brief")
    print("─" * 45)
    from scripts.stage6_negotiate import run
    run(company=args.company, role=args.role, offer=args.offer)


# ── Full morning routine ──────────────────────────────────────

def morning_routine(args):
    """Scrape + score only. Sends a review digest so you can Disregard bad jobs before tailoring."""
    print("\n☀️  MORNING JOB SEARCH PIPELINE")
    print("=" * 45)
    stage1(args)
    stage4(args, mode="scraped")
    print("\n✅ Scrape complete.")
    print("   → Review the digest email / output/review_digest_*.html")
    print("   → Open Notion and set Status = Disregard on jobs to skip")
    print("   → Then run: python run.py --evaluate")


def evaluate_routine(args):
    """Sync Disregard from Notion → Supabase, then tailor + outreach + ready digest."""
    print("\n🔄 EVALUATE — Tailor reviewed jobs")
    print("=" * 45)

    from scripts.utils import sync_notion_to_supabase
    print("\n  Syncing Disregard status from Notion → Supabase...")
    n = sync_notion_to_supabase()
    print(f"  ✓ {n} job(s) marked Disregard in Supabase")

    stage2(args)
    stage3(args)
    stage4(args, mode="ready")
    print("\n✅ Evaluate pipeline complete.")
    print("   → Tailored resumes in output/resumes/")
    print("   → Outreach drafts in output/outreach/")
    print("   → Ready digest in output/digest_*.html")


# ── CLI ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Job Search Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--stage",        type=int, default=None,   help="Run specific stage (1–6)")
    parser.add_argument("--setup",        action="store_true",       help="Check config & dependencies")
    parser.add_argument("--min-score",    type=int, default=0,       help="Min ATS score for tailoring")
    parser.add_argument("--company",      type=str, default=None)
    parser.add_argument("--role",         type=str, default="")
    parser.add_argument("--contact",      type=str, default=None)
    parser.add_argument("--contact-role", type=str, default="",     dest="contact_role")
    parser.add_argument("--jd-file",      type=str, default="",     dest="jd_file")
    parser.add_argument("--hm-linkedin",  type=str, default="",     dest="hm_linkedin")
    parser.add_argument("--offer",        type=float, default=0)
    parser.add_argument("--send",         action="store_true",       help="Send digest via Gmail")
    parser.add_argument("--evaluate",     action="store_true",       help="Sync Disregard from Notion then tailor + outreach + digest")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))

    if args.setup:
        check_setup()
        return

    stages = {1: stage1, 2: stage2, 3: stage3, 4: stage4, 5: stage5, 6: stage6}

    if args.evaluate:
        evaluate_routine(args)
    elif args.stage:
        fn = stages.get(args.stage)
        if not fn:
            print(f"Unknown stage: {args.stage}. Choose 1–6.")
            sys.exit(1)
        fn(args)
    else:
        morning_routine(args)


if __name__ == "__main__":
    main()
