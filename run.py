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
    python run.py --serve [--port 8765]    # Start the Layer 3 browser-extension HTTP bridge
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

# ── First-run wizard (fork onboarding) ────────────────────────

def _upsert_env(path: Path, key: str, value: str) -> None:
    """Set KEY=value in a .env file, in place, without disturbing comments or other lines.

    Replaces the first uncommented `KEY=...` line if present; otherwise appends. Idempotent —
    safe to re-run. Also mirrors the value into os.environ so the current process sees it.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{key}="
    replaced = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(prefix) and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def init_wizard():
    """Interactive fork onboarding: capture Notion connection details, provision the Notion
    page + all three databases, and persist the new ids to a git-ignored .env.

    Idempotent and re-runnable. Non-interactive fallback: hand-edit .env and run
    `python scripts/provision_notion.py --parent-page <id>` directly.
    """
    print("=== Careerpilot-ai — first-run setup ===\n")
    # Side effect only: loads any existing .env into os.environ before the NOTION_API_KEY /
    # NOTION_DB_ID reads below. --init is the one entry point that runs before argparse's normal
    # `import config.settings` elsewhere in main() — without this, a re-run on an already-`init`ed
    # fork would never see its own NOTION_DB_ID and would fall through to re-provisioning.
    import config.settings  # noqa: F401
    env_path = ROOT / ".env"
    if not env_path.exists():
        example = ROOT / ".env.example"
        if example.exists():
            env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print("• Created .env from .env.example\n")
        else:
            env_path.write_text("", encoding="utf-8")

    def _prompt(label: str, current: str = "") -> str:
        shown = f" [{current[:6]}…]" if current else ""
        val = input(f"{label}{shown}: ").strip()
        return val or current

    # 1. Notion API key
    api_key = _prompt("Notion integration token (NOTION_API_KEY)", os.environ.get("NOTION_API_KEY", ""))
    if not api_key:
        print("\n✗ A Notion integration token is required. Create one at "
              "https://www.notion.so/my-integrations, then re-run `python run.py --init`.")
        return 1
    _upsert_env(env_path, "NOTION_API_KEY", api_key)

    # 2. Tracker DB — provision unless one is already configured.
    existing_db = os.environ.get("NOTION_DB_ID", "")
    if existing_db:
        reuse = input(f"\nNOTION_DB_ID is already set ({existing_db[:8]}…). "
                      "Provision a NEW workspace anyway? [y/N]: ").strip().lower()
        if reuse != "y":
            print("• Keeping the existing tracker DB. Skipping provisioning.")
            _profile_wizard(env_path)
            _sync_ci_secrets()
            print("\nRunning a setup check…\n")
            check_setup()
            return 0

    print("\nProvisioning creates a 'Careerpilot-ai' page with three databases under a page you")
    print("choose. First share that page with your integration (open the page → ••• →")
    print("'Connections' → add your integration), then paste its share link below")
    print("(open the page → ••• → 'Copy link'). A raw page id works too.")
    parent = _prompt("\nShared parent page — share link or id").strip()
    if not parent:
        print("\n✗ A shared parent page is required to provision. Re-run when ready.")
        return 1

    try:
        from scripts.provision_notion import provision
        tracker_id, scratch_id, restricted_id = provision(parent)
    except Exception as e:
        print(f"\n✗ Provisioning failed ({e}).")
        print("  Check the token and that the parent page is shared with the integration, then re-run.")
        return 1

    _upsert_env(env_path, "NOTION_DB_ID", tracker_id)
    _upsert_env(env_path, "NOTION_SCRATCH_PAGE_ID", scratch_id)
    _upsert_env(env_path, "NOTION_RESTRICTED_COMPANIES_PAGE_ID", restricted_id)
    print(f"\n✓ Wrote NOTION_DB_ID, NOTION_SCRATCH_PAGE_ID, and "
          f"NOTION_RESTRICTED_COMPANIES_PAGE_ID to {env_path.name}")

    _profile_wizard(env_path)
    _sync_ci_secrets()

    print("\nRunning a setup check…\n")
    check_setup()
    return 0


def _profile_wizard(env_path: Path):
    """Skippable identity-profile block of `--init`: capture name / email / bio / target roles /
    target companies / resume paths / AI provider and write them to a git-ignored
    config/profile.json (seeded from config/profile.example.json if missing).

    Separate and skippable on purpose — the Notion-only onboarding path stays fully usable if the
    forker declines here (they can hand-edit config/profile.json later, or re-run `--init`).
    Prompts pre-fill from the current effective value (Enter keeps it), mirroring
    `--setup-profile`'s ergonomics for the Stage-7 answer wizard.
    """
    import json
    resp = input("\nSet up your identity profile now — name, targets, resume paths, AI "
                 "provider? [Y/n]: ").strip().lower()
    if resp == "n":
        print("• Skipped profile setup — edit config/profile.json by hand or re-run "
              "`python run.py --init`.")
        return

    config_dir = env_path.parent / "config"
    profile_path = config_dir / "profile.json"
    example_path = config_dir / "profile.example.json"

    # Seed: an existing profile.json wins (re-run keeps prior answers), else the tracked example.
    profile: dict = {}
    for seed in (profile_path, example_path):
        if seed.exists():
            try:
                loaded = json.loads(seed.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    profile = loaded
                    break
            except Exception:
                continue

    # Current effective values (generic defaults on a fresh fork) to pre-fill each prompt.
    from config import settings as _s
    cur_name     = profile.get("name")             or getattr(_s, "YOUR_NAME", "")
    cur_email    = profile.get("email")            or getattr(_s, "YOUR_EMAIL", "")
    cur_bio      = profile.get("bio")              or getattr(_s, "YOUR_BIO", "")
    cur_roles    = profile.get("target_roles")     or getattr(_s, "TARGET_ROLES", [])
    cur_cos      = profile.get("target_companies") or getattr(_s, "TARGET_COMPANIES", [])
    cur_resume   = profile.get("resume_path")          or getattr(_s, "RESUME_PATH", "config/resume.txt")
    cur_template = profile.get("resume_template_path") or getattr(_s, "RESUME_TEMPLATE_PATH", "config/resume.docx")
    cur_provider = profile.get("ai_provider")      or getattr(_s, "AI_PROVIDER", "claude")

    def _p(label: str, current: str) -> str:
        val = input(f"  {label} [{current}]: ").strip()
        return val or current

    def _p_list(label: str, current: list) -> list:
        shown = ", ".join(current)
        val = input(f"  {label} (comma-separated) [{shown}]: ").strip()
        if not val:
            return list(current)
        return [item.strip() for item in val.split(",") if item.strip()]

    profile["name"]                 = _p("Full name", cur_name)
    profile["email"]                = _p("Email", cur_email)
    profile["bio"]                  = _p("One-paragraph bio", cur_bio)
    profile["target_roles"]         = _p_list("Target roles", cur_roles)
    profile["target_companies"]     = _p_list("Target companies", cur_cos)
    profile["resume_path"]          = _p("Resume text path", cur_resume)
    profile["resume_template_path"] = _p("Resume .docx path", cur_template)
    profile["ai_provider"]          = _p("AI provider (claude/claude_code/gemini/codex/openrouter)", cur_provider)

    config_dir.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(f"✓ Wrote {profile_path.relative_to(env_path.parent)} (git-ignored).")


def _sync_ci_secrets():
    """Skippable final block of `--init`: push the CI-relevant, non-empty secrets to GitHub
    Actions via the `gh` CLI so the nightly workflow can materialize the git-ignored
    config/profile.json the fork just set up.

    Shells out to `gh` (no new pip dependency, no PyNaCl-encrypted REST path). If `gh` is
    missing or unauthenticated it never raises — it prints the exact `gh secret set …` commands
    for the user to run by hand, then continues.

    Resume files (`RESUME_PATH` / `RESUME_TEMPLATE_PATH`) are NOT synced here — they're tracked
    in git as usual (`config/resume.txt` / `config/resume.docx`), so a CI checkout already has
    them. Keep your resume content in those files up to date locally and commit it like any
    other tracked file.
    """
    resp = input("\nPush your secrets to GitHub Actions via `gh` now (for the nightly "
                 "workflow)? [Y/n]: ").strip().lower()
    if resp == "n":
        print("• Skipped CI secret sync — re-run `python run.py --init`, or set them by hand.")
        return

    # Text secrets sourced from the environment (already loaded from .env by config.settings).
    secrets: dict[str, str] = {}
    for name in ("NOTION_API_KEY", "NOTION_DB_ID", "APIFY_API_TOKEN",
                 "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        val = os.environ.get(name, "")
        if val:
            secrets[name] = val

    profile_path = ROOT / "config" / "profile.json"
    if profile_path.exists():
        text = profile_path.read_text(encoding="utf-8")
        if text.strip():
            secrets["PROFILE_JSON"] = text

    if not secrets:
        print("• No non-empty CI secrets found to sync.")
        return

    # Probe gh: a missing binary raises FileNotFoundError from subprocess; treat as "not ready".
    gh_ready = False
    try:
        ver = subprocess.run(["gh", "--version"], capture_output=True, text=True)
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        gh_ready = ver.returncode == 0 and auth.returncode == 0
    except Exception:
        gh_ready = False

    if gh_ready:
        for name, value in secrets.items():
            try:
                subprocess.run(["gh", "secret", "set", name], input=value, text=True, check=True)
                print(f"  ✓ gh secret set {name}")
            except Exception as e:
                print(f"  ✗ gh secret set {name} failed ({e}) — set it by hand.")
        print("\n✓ CI secrets pushed via gh.")
        return

    # Fallback — print the exact commands, don't raise.
    print("\n⚠  `gh` not found or not authenticated — nothing was pushed.")
    print("   Install the GitHub CLI (https://cli.github.com) and run `gh auth login`, then")
    print("   run these by hand (same values, one manual step):")
    for name in secrets:
        if name == "PROFILE_JSON":
            print("     gh secret set PROFILE_JSON < config/profile.json")
        else:
            print(f"     gh secret set {name} --body \"<your {name}>\"")


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
    CLAUDE_CODE_OAUTH_TOKEN = getattr(_settings, "CLAUDE_CODE_OAUTH_TOKEN", "") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    _cli_found = bool(_cli := (shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")))
    _claude_code_available = _cli_found or bool(CLAUDE_CODE_OAUTH_TOKEN)
    _provider_key = {
        "claude":      ("Anthropic API key", ANTHROPIC_API_KEY, "Set ANTHROPIC_API_KEY in .env (copy .env.example) or your environment"),
        "claude_code": ("Claude Code CLI (subscription)", _claude_code_available, "Install the Claude Code CLI and run `claude /login` (or set CLAUDE_CODE_OAUTH_TOKEN for headless/CI auth)"),
        "gemini":      ("Gemini API key",    GEMINI_API_KEY,    "Set GEMINI_API_KEY in .env (copy .env.example) or your environment"),
        "codex":       ("OpenAI API key",    OPENAI_API_KEY,    "Set OPENAI_API_KEY in .env (copy .env.example) or your environment"),
        "openrouter":  ("OpenRouter API key", OPENROUTER_API_KEY, "Set OPENROUTER_API_KEY in .env (copy .env.example) or your environment"),
    }
    # A missing key for the *configured* tier provider isn't fatal on its own — any other
    # provider's key/CLI being available means a stage can still run via FAST_PROVIDER/
    # QUALITY_PROVIDER or `--ai-mode`. Only flag red if literally none of them are usable.
    _any_provider_available = any(bool(val) for _, val, _ in _provider_key.values())
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

    # Notion tracker: a real schema check, not just "is the id non-empty". A forker who never ran
    # --init has no id; one who provisioned a partial DB has an id that points at a broken schema.
    if not NOTION_DB_ID:
        notion_db_check = ("Notion tracker DB", False,
                           "No NOTION_DB_ID set — run `python run.py --init` to provision one")
    elif not NOTION_API_KEY:
        notion_db_check = ("Notion tracker DB", bool(NOTION_DB_ID),
                           "Set NOTION_API_KEY first, then re-run to validate the schema")
    else:
        try:
            from scripts.provision_notion import validate_schema
            missing = validate_schema(NOTION_DB_ID)
            if missing:
                notion_db_check = ("Notion tracker DB schema", False,
                                   f"{len(missing)} item(s) missing: {', '.join(missing[:6])}"
                                   f"{'…' if len(missing) > 6 else ''} — re-run `python run.py --init`")
            else:
                notion_db_check = ("Notion tracker DB schema", True, "")
        except Exception as e:
            notion_db_check = ("Notion tracker DB schema", False,
                               f"Could not read the DB ({e}) — check the id and that the "
                               "integration is shared with it")

    checks = [
        ("Apify token",     bool(APIFY_API_TOKEN), "Set APIFY_API_TOKEN in .env (copy .env.example) or your environment"),
        ("Notion API key",  bool(NOTION_API_KEY),  "Set NOTION_API_KEY in .env (copy .env.example) or your environment (PRIMARY data store)"),
        notion_db_check,
        ("Resume file",     (ROOT / RESUME_PATH).exists(), f"Add your resume to {RESUME_PATH}"),
    ]
    for tier_provider in dict.fromkeys((FAST_PROVIDER, QUALITY_PROVIDER)):  # dedup, keep order
        key_label, key_val, key_fix = _provider_key.get(
            tier_provider,
            ("Unknown provider key", False, "Set AI_PROVIDER to claude/claude_code/gemini/codex/openrouter in config/settings.py")
        )
        ok = bool(key_val)
        if not ok and _any_provider_available:
            # Soft pass: the configured provider's key is missing, but at least one other
            # provider key/CLI is usable — don't hard-block setup over it.
            available = [_provider_key[p][0] for p in _provider_key if _provider_key[p][1]]
            key_label = f"{key_label} (not set, but usable via: {', '.join(available)})"
            ok = True
        checks.insert(0, (key_label, ok, key_fix))

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


def serve_routine(args):
    """Start the Stage 7 Layer 3 local HTTP bridge (scaffold-only: GET /health)."""
    from scripts.autoapply_server import run_forever
    run_forever(port=args.port)


# ── Full morning routine ──────────────────────────────────────

def ingest_routine(args):
    """Promote scratch-note URL drops to Interested rows, then pull all jobs hand-picked
    in Notion (Status=Interested), score them, and promote them to Scraped — without a
    full LinkedIn scrape."""
    print("\n📥 INGEST — Notion 'Interested' jobs")
    print("=" * 45)
    from scripts.utils import load_resume, NotionReadError
    from scripts.stage1_scrape import ingest_from_scratch_note, ingest_interested_from_notion
    promoted = ingest_from_scratch_note()
    if promoted:
        print(f"   Promoted {promoted} scratch-note URL(s) to Interested")
    try:
        n = ingest_interested_from_notion(load_resume())
    except NotionReadError as e:
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
    parser.add_argument("--serve",        action="store_true",
                        help="Start the Stage 7 Layer 3 local HTTP bridge for the browser extension")
    parser.add_argument("--port",         type=int, default=8765,
                        help="Port for --serve (default 8765)")
    parser.add_argument("--init",         action="store_true",
                        help="One-time fork onboarding: capture Notion details, provision the "
                             "page + databases, write ids to .env")
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

    if args.init:
        sys.exit(init_wizard())

    if args.setup:
        check_setup()
        return

    if args.setup_profile:
        sys.exit(setup_profile_routine(args))

    if args.serve:
        sys.exit(serve_routine(args))

    stages = {1: stage1, 2: stage2, 3: stage3, 4: stage4, 5: stage5, 6: stage6, 7: stage7}

    from scripts.utils import NotionReadError

    # A failed Notion read is turned into a clean message + non-zero exit for *every* entry
    # point here (--ingest already does its own, more specific, version above). Only the typed
    # NotionReadError is caught — the unrelated RuntimeErrors from Apify (scripts/sources.py),
    # provider/CLI setup, or stage 5 keep their existing behavior rather than being mislabeled
    # as a tracker read failure. SystemExit from ingest_routine / unknown-stage passes through.
    try:
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
    except NotionReadError as e:
        print(f"\n❌ Aborted — could not read the Notion tracker: {e}")
        print("   Nothing was changed. Check that NOTION_API_KEY is set and the integration")
        print("   is still shared with the database, then re-run — these routines are idempotent.")
        sys.exit(1)


if __name__ == "__main__":
    main()
