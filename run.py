#!/usr/bin/env python3
"""
run.py — Master pipeline runner
────────────────────────────────
Two-step daily flow:

  Step 1 — Scrape & review (run each morning):
    python run.py                          # Scrape + score → review digest email → STOP
                                           # Open Notion, set Status=Reviewed on jobs to apply

  Step 2 — Tailor reviewed jobs:
    python run.py --evaluate               # Sync Reviewed from Notion → tailor + outreach + digest

  Individual stages:
    python run.py --stage 1               # Scrape only
    python run.py --retry-only            # Re-score 'Retry' jobs only, no new scrape
    python run.py --stage 2 --min-score 65
    python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
    python run.py --stage 4 --send
    python run.py --stage 5 --company "Google" --role "Senior PM"
    python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000
    python run.py --setup-profile          # One-time: capture your application answers
    python run.py --stage 7 --dry-run --limit 3   # Sample it: real sheets, no Notion writes
    python run.py --stage 7                # Auto-apply prep: answer sheets, never submits
    python run.py --stage 7 --fill         # ...and pre-fill the form in a browser
    python run.py --setup                  # Check config & install deps
"""

import os, sys, argparse, subprocess
from pathlib import Path

# Windows terminals default to cp1252; force UTF-8 so emoji/check marks render
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent


# ── Dependency check ──────────────────────────────────────────

# Only the active provider's SDK is required; the others are optional
_PROVIDER_PKGS = {
    "claude":      "anthropic",
    "claude_code": "anthropic",
    "gemini":      "google-generativeai",
    "codex":       "openai",
    "openrouter":  "openai",  # OpenRouter speaks the OpenAI-compatible Chat Completions API
}

def _get_required():
    from config.settings import AI_PROVIDER
    import config.settings as _settings
    fast    = getattr(_settings, "FAST_PROVIDER", "") or AI_PROVIDER
    quality = getattr(_settings, "QUALITY_PROVIDER", "") or AI_PROVIDER
    pkgs = {_PROVIDER_PKGS.get(p, "anthropic") for p in (fast, quality)}
    return sorted(pkgs) + ["notion_client", "requests"]

def check_setup():
    print("=== Setup Check ===\n")
    from config.settings import (
        AI_PROVIDER,
        APIFY_API_TOKEN, NOTION_API_KEY, NOTION_DB_ID,
        RESUME_PATH
    )
    import config.settings as _settings
    # Alternate-provider keys are optional under the default claude_code provider.
    ANTHROPIC_API_KEY  = getattr(_settings, "ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY     = getattr(_settings, "GEMINI_API_KEY", "")
    OPENAI_API_KEY     = getattr(_settings, "OPENAI_API_KEY", "")
    OPENROUTER_API_KEY = getattr(_settings, "OPENROUTER_API_KEY", "")
    FAST_PROVIDER      = getattr(_settings, "FAST_PROVIDER", "") or AI_PROVIDER
    QUALITY_PROVIDER   = getattr(_settings, "QUALITY_PROVIDER", "") or AI_PROVIDER

    import shutil
    _cli_found = bool(shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe"))
    _provider_key = {
        "claude":      ("Anthropic API key", ANTHROPIC_API_KEY, "Set ANTHROPIC_API_KEY in .env (copy .env.example) or your environment"),
        "claude_code": ("Claude Code CLI (subscription)", _cli_found, "Install the Claude Code CLI and run `claude /login` (or set CLAUDE_CODE_OAUTH_TOKEN for headless/CI auth)"),
        "gemini":      ("Gemini API key",    GEMINI_API_KEY,    "Set GEMINI_API_KEY in .env (copy .env.example) or your environment"),
        "codex":       ("OpenAI API key",    OPENAI_API_KEY,    "Set OPENAI_API_KEY in .env (copy .env.example) or your environment"),
        "openrouter":  ("OpenRouter API key", OPENROUTER_API_KEY, "Set OPENROUTER_API_KEY in .env (copy .env.example) or your environment"),
    }
    from scripts.utils import _resolve_model
    fast_model    = _resolve_model(False, FAST_PROVIDER)
    quality_model = _resolve_model(True, QUALITY_PROVIDER)

    if FAST_PROVIDER == QUALITY_PROVIDER:
        # Same provider — model may still differ between tiers (e.g. Haiku vs Sonnet).
        # Use the resolved tier provider (not the raw AI_PROVIDER default) so a
        # FAST_PROVIDER/QUALITY_PROVIDER env override is reflected accurately.
        print(f"  AI provider : {FAST_PROVIDER}  (fast: {fast_model}, quality: {quality_model})\n")
    else:
        print(f"  AI routing  : fast={FAST_PROVIDER} ({fast_model}, stages 1,3)  |  "
              f"quality={QUALITY_PROVIDER} ({quality_model}, stages 2,5,6)\n")

    checks = [
        ("Apify token",     bool(APIFY_API_TOKEN), "Set APIFY_API_TOKEN in .env (copy .env.example) or your environment"),
        ("Notion API key",  bool(NOTION_API_KEY),  "Set NOTION_API_KEY in .env (copy .env.example) or your environment (PRIMARY data store)"),
        ("Notion DB ID",    bool(NOTION_DB_ID),    "Already set — your tracker DB"),
        ("Resume file",     (ROOT / RESUME_PATH).exists(), f"Add your resume to {RESUME_PATH}"),
    ]
    for tier_provider in dict.fromkeys((FAST_PROVIDER, QUALITY_PROVIDER)):  # dedup, keep order
        key_label, key_val, key_fix = _provider_key.get(
            tier_provider,
            ("Unknown provider key", False, "Set AI_PROVIDER to claude/claude_code/gemini/codex/openrouter in config/settings.py")
        )
        checks.insert(0, (key_label, bool(key_val), key_fix))

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

    if NOTION_API_KEY and NOTION_DB_ID:
        try:
            from scripts.utils import db_get_jobs
            retry_count = len(db_get_jobs(status="Retry"))
            print(f"\n  Retry queue: {retry_count} job(s) awaiting re-score")
        except Exception as e:
            print(f"\n  Retry queue: could not check ({e})")

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
    run(target_company=args.company, contact=args.contact, contact_role=args.contact_role,
        no_confirm=args.no_confirm)

def stage4(args, mode: str = "ready"):
    print("\n📋 STAGE 4 — Morning digest")
    print("─" * 45)
    from scripts.stage4_digest import run
    run(send=args.send, mode=mode)

def stage5(args):
    print("\n🎯 STAGE 5 — Interview prep guide")
    print("─" * 45)
    from scripts.stage5_interview_prep import run
    run(company=args.company, role=args.role, jd_file=args.jd_file, hm_linkedin=args.hm_linkedin,
        no_confirm=args.no_confirm)

def stage6(args):
    print("\n💰 STAGE 6 — Salary negotiation brief")
    print("─" * 45)
    from scripts.stage6_negotiate import run
    run(company=args.company, role=args.role, offer=args.offer)

def stage7(args):
    print("\n📮 STAGE 7 — Auto-apply prep (never submits)")
    print("─" * 45)
    from scripts.autoapply import run
    run(min_score=args.min_score, fill=args.fill, limit=args.limit, dry_run=args.dry_run)


def setup_profile_routine(args):
    """One-time interactive capture of the Stage 7 application answers."""
    from scripts.autoapply_profile import main as profile_main
    return profile_main([])


# ── Full morning routine ──────────────────────────────────────

def ingest_routine(args):
    """Promote scratch-note URL drops to Interested rows, then pull all jobs hand-picked
    in Notion (Status=Interested), score them, and promote them to Scraped — without a
    full LinkedIn scrape."""
    print("\n📥 INGEST — Notion 'Interested' jobs")
    print("=" * 45)
    from scripts.utils import load_resume
    from scripts.stage1_scrape import ingest_from_scratch_note, ingest_interested_from_notion
    promoted = ingest_from_scratch_note()
    if promoted:
        print(f"   Promoted {promoted} scratch-note URL(s) to Interested")
    try:
        n = ingest_interested_from_notion(load_resume())
    except RuntimeError as e:
        # The Notion readers raise on a failed read rather than reporting an empty result
        # (see db_get_all_jobs' contract). Surface that as a clean message + non-zero exit
        # instead of a traceback: "Ingested 0 jobs" on an unreadable tracker is the exact
        # silent-success this pipeline treats as unacceptable, and the nightly workflow
        # needs the non-zero exit to actually fail the run.
        print(f"\n❌ Ingest aborted — could not read the Notion tracker: {e}")
        print("   Nothing was changed. Check NOTION_API_KEY and that the integration is")
        print("   still shared with the database, then re-run — ingest is idempotent.")
        sys.exit(1)
    print(f"\n✅ Ingested {n} 'Interested' job(s) → Scraped.")
    print("   → Review them in Notion, set Status=Reviewed, then run: python run.py --evaluate")


def retry_routine(args):
    """Re-score only the jobs stuck in Status=Retry from their already-cached JD —
    no Apify call, no scrape of new roles."""
    print("\n🔁 RETRY — Re-score 'Retry' jobs")
    print("=" * 45)
    from scripts.utils import load_resume
    from scripts.stage1_scrape import rescore_retry_jobs
    counters = rescore_retry_jobs(load_resume())
    print(
        f"\n✅ Retry pass complete: {counters['recovered']} recovered, "
        f"{counters['filtered']} filtered, {counters['given_up']} given up, "
        f"{counters['still_retrying']} still retrying."
    )


def morning_routine(args):
    """Scrape + score only. Sends a review digest so you can mark good jobs as Reviewed before tailoring."""
    print("\n☀️  MORNING JOB SEARCH PIPELINE")
    print("=" * 45)
    stage1(args)
    stage4(args, mode="scraped")
    print("\n✅ Scrape complete.")
    print("   → Review the digest email / output/review_digest_*.html")
    print("   → Open Notion and set Status = Reviewed on jobs to apply")
    print("   → Then run: python run.py --evaluate")


def evaluate_routine(args):
    """Tailor 'Reviewed' jobs (read straight from Notion), then outreach + ready digest."""
    print("\n🔄 EVALUATE — Tailor reviewed jobs")
    print("=" * 45)
    print("\n  Reading 'Reviewed' jobs directly from Notion (primary store)...")

    stage2(args)
    # Pass no_confirm so --evaluate runs non-interactively; drafts saved, user marks manually
    from scripts.stage3_outreach import run as _stage3_run
    _stage3_run(target_company=args.company, contact=args.contact, contact_role=args.contact_role, no_confirm=True)
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
    parser.add_argument("--stage",        type=int, default=None,   help="Run specific stage (1–7)")
    parser.add_argument("--fill",         action="store_true",
                        help="Stage 7: also pre-fill the form in a browser (stops before submit)")
    parser.add_argument("--dry-run",      action="store_true", dest="dry_run",
                        help="Stage 7: plan and write answer sheets, but make NO Notion writes")
    parser.add_argument("--limit",        type=int, default=0,
                        help="Stage 7: cap how many jobs to process this run (overrides AUTOAPPLY_DAILY_CAP)")
    parser.add_argument("--setup-profile", action="store_true", dest="setup_profile",
                        help="One-time interactive setup of your Stage 7 application answers")
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
    parser.add_argument("--evaluate",     action="store_true",       help="Sync Reviewed jobs from Notion then tailor + outreach + digest")
    parser.add_argument("--ingest",       action="store_true",       help="Promote scratch-note URL drops + ingest Notion 'Interested' jobs (score + promote to Scraped)")
    parser.add_argument("--retry-only",   action="store_true",       dest="retry_only",
                         help="Re-score only Status='Retry' jobs from their cached JD (no scrape of new roles)")
    parser.add_argument("--no-confirm",   action="store_true",       dest="no_confirm",
                         help="Skip interactive y/n confirmations and manual-paste prompts "
                              "(required for unattended runs, e.g. --stage 3 or --stage 5 in CI — "
                              "without it those stages call input() and hang/crash on a closed stdin)")
    parser.add_argument(
        "--ai-mode", type=str, default=None,
        choices=["metered", "hybrid", "subscription"],
        help="Override AI provider routing for this run: "
             "metered = the --metered-provider backend everywhere, "
             "hybrid = the --metered-provider backend for fast/bulk calls + claude_code "
             "(subscription) for quality calls, "
             "subscription = claude_code everywhere",
    )
    parser.add_argument(
        "--metered-provider", type=str, default="claude", dest="metered_provider",
        choices=["claude", "codex", "gemini", "openrouter"],
        help="Which metered API backend --ai-mode metered/hybrid uses for their non-subscription "
             "tier(s): claude=Anthropic API, codex=OpenAI, gemini=Google Gemini, "
             "openrouter=OpenRouter (any model behind one key). Defaults to claude; ignored "
             "without --ai-mode and ignored by --ai-mode subscription.",
    )
    args = parser.parse_args()

    if args.ai_mode:
        _AI_MODE_PROVIDERS = {
            "metered":      (args.metered_provider, args.metered_provider),
            "hybrid":       (args.metered_provider, "claude_code"),
            "subscription": ("claude_code",          "claude_code"),
        }
        fast, quality = _AI_MODE_PROVIDERS[args.ai_mode]
        os.environ["FAST_PROVIDER"] = fast
        os.environ["QUALITY_PROVIDER"] = quality

    sys.path.insert(0, str(ROOT))

    if args.setup:
        check_setup()
        return

    if args.setup_profile:
        sys.exit(setup_profile_routine(args))

    stages = {1: stage1, 2: stage2, 3: stage3, 4: stage4, 5: stage5, 6: stage6, 7: stage7}

    if args.ingest:
        ingest_routine(args)
    elif args.retry_only:
        retry_routine(args)
    elif args.evaluate:
        evaluate_routine(args)
    elif args.stage:
        fn = stages.get(args.stage)
        if not fn:
            print(f"Unknown stage: {args.stage}. Choose 1–7.")
            sys.exit(1)
        fn(args)
    else:
        morning_routine(args)


if __name__ == "__main__":
    main()
