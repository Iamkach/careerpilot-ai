# ============================================================
#  config/settings.py  —  Fill these in before running
# ============================================================

import os
from pathlib import Path


def _load_local_env(path=Path(__file__).resolve().parent.parent / ".env"):
    # Local-only convenience: GitHub Actions supplies secrets via `secrets.*` env vars
    # (see .github/workflows/nightly-pipeline.yml), so this is a no-op in CI even if a
    # stray .env exists. setdefault() means a real env var always wins over the file.
    if os.environ.get("GITHUB_ACTIONS") or not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()

# --- Your profile -------------------------------------------
YOUR_NAME        = "Krishna Achyuth"
YOUR_EMAIL       = "kachyuth06@gmail.com"
YOUR_BIO         = "Senior Software Engineer with deep experience building scalable, reliable products across backend, full-stack, and cloud systems. I bring strong technical execution, product-minded judgment, and a track record of turning complex requirements into maintainable software that moves business outcomes."

# --- Job search targets -------------------------------------
TARGET_ROLES     = ["Software Engineer", "Senior Software Engineer", "Backend Engineer", "Full Stack Engineer", "Staff Software Engineer"]  # list of 2-3 roles you're targeting
# Search is always US-wide. Jobs are filtered to US locations post-scrape.
# Seeds scripts/sources.py's discover_tokens() (Greenhouse/Lever/Ashby board-token probing) —
# union'd at runtime with every distinct company already in the Notion DB.
TARGET_COMPANIES = ["Google", "Meta", "Stripe", "Notion", "Figma"]

# --- Multi-source sourcing (stage 1, Step 6 Phase 1) ---------
# Which scripts/sources.py registry entries run each scrape. Keyword sources
# (linkedin, indeed) search TARGET_ROLES; board sources (greenhouse, lever, ashby) crawl
# each TARGET_COMPANIES company's own board via config/ats_tokens.json.
ENABLED_SOURCES = ["linkedin", "indeed", "greenhouse", "lever", "ashby"]

# Jobs older than this (by posted_date) are dropped as "stale" in _pre_filter.
MAX_JOB_AGE_DAYS = 14

# A source that doesn't expose a post date (posted_date=None) is kept by default — flip to
# True to drop undated listings instead of assuming they're fresh.
DROP_UNDATED_JOBS = False

# --- Company denylist (stage 1) -----------------------------
# Two-layer filter:
#   SKIP_COMPANIES — word-boundary token sub-sequence match (case-insensitive), not a
#     raw substring match. "UST" won't match "Customer.io"; "Tata Consultancy" still
#     matches "Tata Consultancy Services". Trailing legal suffixes (Inc/LLC/Corp/...)
#     are ignored, so "BeaconFire Inc." matches bare "BeaconFire".
#   SKIP_COMPANY_KEYWORDS — loose substring/phrase match, on purpose (catches unnamed
#     firms via generic patterns like "solutions llc").
# Grow SKIP_COMPANIES over time as you spot new offenders.

SKIP_COMPANIES = [
    # Big consulting / IT services — named explicitly to avoid false positives
    "Accenture", "Deloitte", "Cognizant", "Tata Consultancy", "TCS", "Infosys",
    "Wipro", "Capgemini", "HCL Technologies", "HCL Tech", "Tech Mahindra",
    "NTT DATA", "Hexaware", "Mphasis", "LTIMindtree", "Mindtree", "Genpact",
    "DXC Technology", "Birlasoft", "Coforge", "EPAM Systems", "GlobalLogic",
    "Persistent Systems", "Zensar", "Cyient", "Mastech Digital", "iGate",
    "Unison", "Synechron", "Kellton Tech", "Xoriant", "Softchoice", "Softchoice Corp",
    "CGI Inc", "CGI Group", "Leidos", "SAIC", "Booz Allen", "ManTech",
    "Peraton", "Jacobs Engineering", "CACI International",
    # Staffing / recruiting / job reposters
    "Jobs via Dice", "Dice", "Robert Half", "TalentAlly", "Mastech",
    "Compunnel", "Lorven", "VBeyond", "InfoVision", "Bright Vision",
    "Simpalm", "hackajob", "Insight Global", "TEKsystems", "Randstad",
    "Kforce", "CyberCoders", "Apex Systems", "Collabera", "Diverse Lynx",
    "Motion Recruitment", "Piper Companies", "Signature Consultants",
    "iSpace", "Stefanini", "Softpath System", "Vsoft Corporation",
    "Akraya", "Yochana IT", "Sapient", "Publicis Sapient",
    "Precision Technologies", "CapTech", "UST", "UST Global",
    "Veteran Benefits Guide", "Numero", "Haveron James", "Penn State ARL",
    "Accenture Federal Services", "Togetherwork", "Winaxis LLC", "Iron EagleX",
    "BeaconFire Inc.", "Reflexive Concepts",
]

# Keyword patterns — any company whose name contains one of these words/phrases
# (case-insensitive) is treated as a consulting/staffing/service firm.
# Add to this list instead of SKIP_COMPANIES for generic pattern matches.
SKIP_COMPANY_KEYWORDS = [
    # Service / outsourcing signals
    "consulting", "consultancy", "consultants",
    "staffing", "staff augmentation",
    "outsourcing", "outsourced",
    "it services", "managed services", "professional services",
    "solutions llc", "solutions inc", "solutions corp", "solutions group",
    "systems llc", "systems inc",
    "technologies llc", "technologies inc",
    "tech services", "tech solutions",
    "global services", "digital services",
    "resource", "resources",        # "IT Resources LLC", "Global Resources Inc"
    "recruiters", "recruitment",
    "talent", "talents",            # "Talent XYZ", "TalentBridge"
    "placement",
    "workforce",
    "manpower",
    "contractors", "contracting",
    "enterprise solutions",
    "business solutions",
    "it consulting",
]

# Job title denylist — roles that signal staffing/non-product postings.
# Matched case-insensitively as a substring of the job title.
SKIP_TITLE_KEYWORDS = [
    "consultant",       # "Java Consultant", "IT Consultant"
    "contractor",
    "contract role",
    "w2 only",
    "c2c",              # corp-to-corp
    "1099",
    "staffing",
    "recruiter",
    "sourcer",
    "scrum master",     # optional — remove if you want these
    "project manager",  # optional
]

# --- LinkedIn Premium (stage 1) -----------------------------
# Unused since the Step 1 sourcing spike moved Stage 1 to valig~linkedin-jobs-scraper,
# whose schema has no cookie field — it returns applicant_count and salary without one.
# Kept in case a future actor swap needs it again.
LINKEDIN_SESSION_COOKIE = ""   # e.g. "AQEDARxxxxxxxxxxxxxxxx"

# Drop jobs with more than this many applicants (high competition).
# Set to 0 to disable the filter.
MAX_APPLICANT_COUNT = 200

# --- Visa sponsorship filter (stage 1) ----------------------
# When True, stage 1 skips jobs whose JD EXPLICITLY rules out sponsorship
# (e.g. "no visa sponsorship", "must be authorized to work without sponsorship",
# "US citizenship required", "active security clearance required").
# Jobs that say they sponsor OR are silent on the topic are kept.
EXCLUDE_NO_SPONSORSHIP = True

# --- Sponsorship gate (stage 1 + stage 2) ---------------------
# Fallback/escape hatch for the restricted-sponsorship company check -- companies known
# (from your own research/contacts) to sponsor only EXISTING employees (e.g. H-1B
# transfers), not new external hires -- even when the JD reads as sponsorship-friendly or
# says nothing. The PRIMARY/expected way to manage this list is the Notion database at
# NOTION_RESTRICTED_COMPANIES_PAGE_ID above (visual, no redeploy); this hardcoded list is
# merged (OR'd) with it via get_restricted_sponsorship_companies() in scripts/utils.py, for
# when Notion is unreachable or before that database exists. Stage 1 drops a matching
# company silently at scrape time (like SKIP_COMPANIES); stage 2's _sponsorship_gate() also
# checks the same merged list as defense-in-depth, moving a matching "Reviewed" job to
# "Human Review" instead of tailoring a resume for it, in case a job reached "Reviewed"
# before its company was added. Once you've personally confirmed the company will sponsor a
# NEW hire, add SPONSORSHIP_CONFIRMED_MARKER to that job's Notion "Notes" field and move
# Status back to "Reviewed" to release it. Matched using the same word-boundary token
# matching as SKIP_COMPANIES.
RESTRICTED_SPONSORSHIP_COMPANIES = [
    # e.g. "Example Corp",   # sponsors H-1B transfers only, per recruiter YYYY-MM-DD
]

SPONSORSHIP_CONFIRMED_MARKER = "sponsorship confirmed"

# --- ATS score filter (stage 1) ------------------------------
# Jobs scoring below this are scored but not saved to Notion.
# Set to 0 to disable the filter.
MIN_ATS_SCORE = 30

# --- Auto-review gate (stage 1) -------------------------------
# Jobs at/above this ATS score skip the manual Scraped→Reviewed gate and land in "Reviewed"
# directly, unless the JD explicitly rules out sponsorship (see stage1 _auto_review_status).
# Silence on sponsorship is NOT treated as a red flag -- most companies willing to sponsor
# simply don't mention it in the JD. Only Sponsorship="no" (explicit) or a lower score keeps
# a job in "Scraped" for a human second-eye pass.
AUTO_REVIEW_MIN_SCORE = 35

# --- Scoring reliability (stage 1) ----------------------------
# A job whose AI scoring call fails (after ai_chat's internal retries) is written to Notion
# with Status="Retry" and an empty ATS score instead of the old fabricated score=50. It is
# re-scored from its already-cached JD (no repeat Apify call) at the top of every stage 1 run
# via rescore_retry_jobs(). After this many failed scoring passes, it's given up on and
# promoted to "Scraped" with an empty score rather than retried forever.
MAX_SCORING_ATTEMPTS = 3

# --- Enrichment reliability ("Interested" intake) --------------
# A hand-picked "Interested" job whose URL enrichment fails (enrich_job_url() returns None or
# no description -- e.g. a JS-rendered career page generic_url_fetch() can't extract text
# from) is left as "Interested" and retried on the next --ingest run. After this many failed
# enrichment passes, it's given up on and promoted to "Scraped" with a Notes marker asking the
# human to add the JD manually, rather than retried forever. Mirrors MAX_SCORING_ATTEMPTS.
MAX_ENRICHMENT_ATTEMPTS = 3

# Company types the scoring call classifies via `company_type` (in addition to score/
# sponsorship) that should be dropped like a SKIP_COMPANIES hit. Deliberately does NOT
# include "agency" (recruiting agencies sometimes post real product-company roles) — only
# "staffing_or_consulting" firms, which SKIP_COMPANIES can't catch by name alone.
SKIP_COMPANY_TYPES = {"staffing_or_consulting"}

# --- Tailoring verification (stage 2) -------------------------
# After applying edits, stage 2 re-scores the tailored resume against the same JD (reusing
# stage 1's scoring contract) and logs a warning if it lands below this. Non-blocking —
# does not change Notion status or retry tailoring, just surfaces a weak result in the logs.
MIN_TAILORED_ATS_SCORE = 75

# --- Auto-Apply subsystem (stage 7, Step 10) ------------------
# The structured source of truth for every deterministic application answer.
#
# GOVERNING RULE (enforced in code, not by prompt wording): facts come from here; AI only ever
# drafts free-text prose. The model NEVER invents an answer to work-authorization, sponsorship,
# salary, or any yes/no eligibility question — a wrong answer to one of those is disqualifying
# and unretractable. Anything unmapped becomes review_required, never a guess.
#
# A None/empty value is not a bug: it deliberately forces that field to human review.
APPLICATION_PROFILE = {
    # Identity
    "first_name":    "Krishna",
    "last_name":     "Achyuth",
    "full_name":     YOUR_NAME,
    "email":         YOUR_EMAIL,
    "phone":         "",                 # empty -> review_required if a form asks
    "location":      "",
    # Links
    "linkedin_url":  "",
    "github_url":    "",
    "portfolio_url": "",
    # Eligibility facts — deterministic, never model-guessed. Set to None to force review.
    "work_authorized":      True,
    "requires_sponsorship": True,
}

# Structured mailing address. Split out from APPLICATION_PROFILE's freeform `location` because
# real ATS forms (confirmed live on Greenhouse) ask these as discrete fields, not one string.
# The legal name here may differ from APPLICATION_PROFILE's first_name/last_name (a resume/
# outreach display name) — this is the name as it appears on government ID.
APPLICATION_ADDRESS = {
    "legal_first_name": "",
    "legal_last_name":  "",
    "address_line1":    "",
    "address_line2":    "",
    "city":              "",
    "state":             "",
    "country":           "",
    "zip_code":          "",
    "address_type":      "",
}

# EEO / demographic presets. Per spec §7 these default to declining rather than being guessed —
# never let a model infer a protected attribute. Edit any value to a real answer if you prefer to
# disclose; the exact string must match one of the form's offered options to be selectable.
EEO_RESPONSES = {
    "gender":     "Decline To Self Identify",
    "race":       "Decline To Self Identify",
    "ethnicity":  "Decline To Self Identify",
    "veteran":    "I don't wish to answer",
    "disability": "I don't wish to answer",
}

# The recurring screener questions almost every application asks, answered once here instead of
# retyped per job. Keys are lowercase substrings matched against the form's question label (first
# match wins, so order matters — put more specific patterns first). An empty value means "I have
# no preset answer", which routes that field to human review rather than inventing one.
COMMON_QUESTION_PRESETS = {
    "years of experience":   "",
    "notice period":         "",
    "salary expectation":    "",
    "desired salary":        "",
    "expected compensation": "",
    "willing to relocate":   "",
    "remote":                "",
    "start date":            "",
    "available to start":    "",
    "how did you hear":      "Company website",
    "referred by":           "",
    "previously worked":     "No",
    "previously applied":    "No",
}


def _apply_saved_profile():
    """Overlay config/application_profile.json (written by `run.py --setup-profile`) onto the
    three dicts above.

    The defaults above stay as the checked-in fallback; your actual answers live in a
    git-ignored JSON file so personal details never enter version control and you never have to
    edit this module to change a notice period. A missing or corrupt file is a no-op — the
    defaults simply stand — so a bad file can never break a pipeline run.
    """
    import json
    path = Path(__file__).resolve().parent / "application_profile.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(saved, dict):
        return
    for section, target in (("profile", APPLICATION_PROFILE),
                            ("presets", COMMON_QUESTION_PRESETS),
                            ("eeo", EEO_RESPONSES),
                            ("address", APPLICATION_ADDRESS)):
        values = saved.get(section)
        if isinstance(values, dict):
            target.update(values)


_apply_saved_profile()

# Applications prepared per day. This is not only ban-avoidance: ATSes now score application
# velocity and flag high-volume submitters as "low intent" before a human reads the application,
# so a low cap protects application *quality*, not just the account. Keep it small on purpose.
AUTOAPPLY_DAILY_CAP = 10

# Run the stage-7 form fill in a headless browser. Default False — the whole point of the
# semi-auto path is that you watch the filled form and click Submit yourself.
AUTOAPPLY_HEADLESS = False

# --- Resume -------------------------------------------------
# Upload your resume as a .txt or .md file and set path here
RESUME_PATH      = "config/resume.txt"
GDRIVE_RESUME_ID = ""    # Optional: Google Drive file ID of master resume
# Base resume .docx used as the source for tailoring (stage 2). The pipeline
# copies this file and applies targeted ATS keyword edits in-place, preserving
# all formatting. Must be a plain Word document (no Jinja2 placeholders needed).
RESUME_TEMPLATE_PATH = "config/Achyuth_Resume.docx"

# --- AI Provider --------------------------------------------
# Choose which LLM powers all pipeline stages (run.py is the only entry point in use).
# Options: "claude" (metered API) | "claude_code" (subscription) | "gemini" | "codex" | "openrouter"
#
# "claude" calls the metered Anthropic API directly (requires ANTHROPIC_API_KEY below).
# No Claude Code CLI login or session-window limit — every stage script (via ai_chat())
# runs independently of any subscription session, and prompt caching is enabled.
AI_PROVIDER = "codex"

# Optional: route stage scripts (run.py path) through a different provider than AI_PROVIDER.
# Leave blank to fall through to AI_PROVIDER above (default behavior).
STAGE_AI_PROVIDER = ""

# Optional two-tier hybrid routing (e.g. for an unattended nightly GitHub Actions run, where
# a subscription's usage-window cost no longer competes with interactive daytime use).
# FAST_PROVIDER handles many small calls (stage 1 scoring, stage 3 outreach) — keep this on
# "claude" (metered) so prompt caching applies and the run isn't bounded by a session window.
# QUALITY_PROVIDER handles few, larger calls (stage 2 tailor, stage 5/6) — can be switched to
# "claude_code" (subscription) once ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN + `claude
# setup-token` are set up for headless auth. Both default to AI_PROVIDER's value, matching
# today's all-metered behavior for local/manual runs; only overridden when the env vars below
# are set (e.g. in the GitHub Actions workflow env). Interactively, `python run.py
# --ai-mode {metered,hybrid,subscription}` sets these same two env vars for a single run
# without editing this file.
FAST_PROVIDER    = os.environ.get("FAST_PROVIDER", "") or AI_PROVIDER
QUALITY_PROVIDER = os.environ.get("QUALITY_PROVIDER", "") or AI_PROVIDER

# Model overrides for the "claude" provider only — leave blank to use claude-opus-4-6.
# NOTE: these are NOT applied to gemini/codex/claude_code — a Claude model id (e.g.
# "claude-sonnet-5") is meaningless to those SDKs. If you switch AI_PROVIDER (or
# FAST_PROVIDER/QUALITY_PROVIDER) to "gemini" or "codex", that provider automatically falls
# back to its own built-in default (gemini-2.0-flash / gpt-4o) unless you add an entry to
# MODEL_OVERRIDES below — you do NOT need to touch these two fields when switching providers.
AI_MODEL_OVERRIDE = "claude-haiku-4-5-20251001"   # fast/cheap — stages 1, 3 (claude only)
QUALITY_MODEL     = "claude-sonnet-5"             # strong — stages 2, 5, 6 (claude only)

# Per-provider model overrides for gemini/codex/openrouter/claude_code — keyed by provider,
# each with "fast" (stages 1/3) and "quality" (stages 2/5/6) entries. Blank/missing falls back
# to that backend's built-in default (see _DEFAULTS in scripts/utils.py). This is what makes
# switching AI_PROVIDER (or a single tier via FAST_PROVIDER/QUALITY_PROVIDER) to gemini/codex/
# openrouter safe to do at any time — the right model comes along with the provider instead of
# being a separate, easy-to-forget field. OpenRouter model ids are "<vendor>/<model>" (see
# https://openrouter.ai/models) — its own default is the "openrouter/auto" router if unset.
MODEL_OVERRIDES = {
    # "gemini":     {"fast": "gemini-2.0-flash",        "quality": "gemini-1.5-pro"},
    # "codex":      {"fast": "gpt-4o-mini",             "quality": "gpt-4o"},
    # "openrouter": {"fast": "openai/gpt-4o-mini",      "quality": "anthropic/claude-3.5-sonnet"},
}

# --- API Keys -----------------------------------------------
APIFY_API_TOKEN   = os.environ.get("APIFY_API_TOKEN", "")   # set in your env — https://apify.com (free token)
NOTION_API_KEY    = os.environ.get("NOTION_API_KEY", "")   # set in your env (the integration token; DB is shared & working)
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")   # set in your env (metered API key for AI_PROVIDER="claude")
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")   # set in your env (required for AI_PROVIDER="gemini")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")   # set in your env (required for AI_PROVIDER="codex")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")   # set in your env (required for AI_PROVIDER="openrouter" — https://openrouter.ai)
HUNTER_API_KEY    = os.environ.get("HUNTER_API_KEY", "")   # set in your env (Step 7 Phase 0 spike — Hunter.io email finder/verifier)

# --- Step 7 Phase 0 spike (communications subsystem) ---------
# Apify actor id for LinkedIn job-poster/recruiter discovery (coregent, no li_at cookie needed).
# See scripts/spike_phase0_leads.py and docs/backlog/step-7-communications-subsystem.md.
LEAD_ACTOR = "coregent~linkedin-recruiter-job-poster-finder"

# --- Notion IDs (env-sourced — set by `python run.py --init`) ------------------
# Your "Job Search Tracker" database id. No hardcoded default: a fork provisions its own DB
# (python run.py --init, which calls scripts/provision_notion.py) and the id is written to the
# git-ignored .env. Existing owners: put your id in .env once — `python run.py --setup` flags it
# if unset. (See docs/refinement-plans/onboarding/forkable-setup.md.)
NOTION_DB_ID      = os.environ.get("NOTION_DB_ID", "")   # Job Search Tracker

# --- Notion scratch-note intake (optional) -------------------
# Database id of a small Notion database (a "list" view works well) where each row's
# title is one job URL -- fast to add from mobile (tap "+ New", paste the link). Optional
# -- if unset, ingest_from_scratch_note() is a no-op. Create the database once, share it
# with the integration, paste its id here.
NOTION_SCRATCH_PAGE_ID = os.environ.get("NOTION_SCRATCH_PAGE_ID", "")

# --- Notion restricted-sponsorship company list (optional) ---
# Database id of a small Notion database (a "list" view works well) where each row's title
# is one company name known to sponsor only existing employees, not new hires -- add/remove
# entries visually in Notion, no code change or redeploy needed. Primary source for the
# restricted-company check in scripts/stage1_scrape.py (silent drop, like SKIP_COMPANIES)
# and scripts/stage2_tailor.py's _sponsorship_gate() (Human Review defense-in-depth for a
# job that reached "Reviewed" before its company was added). Optional -- if unset,
# get_restricted_companies_from_notion() returns []; RESTRICTED_SPONSORSHIP_COMPANIES below
# still applies as a fallback. Create the database once, share it with the integration,
# paste its id here.
NOTION_RESTRICTED_COMPANIES_PAGE_ID = os.environ.get("NOTION_RESTRICTED_COMPANIES_PAGE_ID", "")

# --- Gmail (optional — for digest emails) -------------------
# Set up via Google Cloud OAuth credentials
GMAIL_CREDENTIALS_PATH = "config/gmail_credentials.json"
DIGEST_RECIPIENT_EMAIL = YOUR_EMAIL

# --- LinkedIn Premium InMail (stage 3) ----------------------
# ATS score threshold above which an InMail draft is generated
# (in addition to / instead of a cold email).
# LinkedIn Career gives 5 InMail credits/month — use them on your best-fit jobs.
INMAIL_ATS_THRESHOLD = 70

# --- Output dirs --------------------------------------------
OUTPUT_DIR        = "output"
RESUMES_DIR       = "output/resumes"
PREP_GUIDES_DIR   = "output/prep_guides"
# Stage 7 answer sheets + filled-form screenshots.
APPLICATIONS_DIR  = "output/applications"
