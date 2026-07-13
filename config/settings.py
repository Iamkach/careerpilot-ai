# ============================================================
#  config/settings.py  —  Fill these in before running
# ============================================================

import os

# --- Your profile -------------------------------------------
YOUR_NAME        = "Krishna Achyuth"
YOUR_EMAIL       = "kachyuth06@example.com"
YOUR_BIO         = "2-line professional bio used in outreach emails" #TODO: write a concise, compelling bio that highlights your experience and value proposition as a Senior Software Engineer.

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

# --- Sponsorship gate (stage 2) ------------------------------
# Product companies known (from your own research/contacts) to sponsor only EXISTING
# employees (e.g. H-1B transfers), not new external hires -- even when the JD reads as
# sponsorship-friendly or says nothing. Unlike SKIP_COMPANIES, these are NOT excluded in
# stage 1 -- still scraped, scored, tracked normally. Stage 2 instead moves a matching
# "Reviewed" job to "Human Review" instead of tailoring a resume for it. Once you've
# personally confirmed the company will sponsor a NEW hire, add SPONSORSHIP_CONFIRMED_MARKER
# to that job's Notion "Notes" field and move Status back to "Reviewed" to release it.
# Matched using the same word-boundary token matching as SKIP_COMPANIES.
RESTRICTED_SPONSORSHIP_COMPANIES = [
    # e.g. "Example Corp",   # sponsors H-1B transfers only, per recruiter YYYY-MM-DD
]

SPONSORSHIP_CONFIRMED_MARKER = "sponsorship confirmed"

# --- ATS score filter (stage 1) ------------------------------
# Jobs scoring below this are scored but not saved to Notion.
# Set to 0 to disable the filter.
MIN_ATS_SCORE = 30

# --- Scoring reliability (stage 1) ----------------------------
# A job whose AI scoring call fails (after ai_chat's internal retries) is written to Notion
# with Status="Retry" and an empty ATS score instead of the old fabricated score=50. It is
# re-scored from its already-cached JD (no repeat Apify call) at the top of every stage 1 run
# via rescore_retry_jobs(). After this many failed scoring passes, it's given up on and
# promoted to "Scraped" with an empty score rather than retried forever.
MAX_SCORING_ATTEMPTS = 3

# Company types the scoring call classifies via `company_type` (in addition to score/
# sponsorship) that should be dropped like a SKIP_COMPANIES hit. Deliberately does NOT
# include "agency" (recruiting agencies sometimes post real product-company roles) — only
# "staffing_or_consulting" firms, which SKIP_COMPANIES can't catch by name alone.
SKIP_COMPANY_TYPES = {"staffing_or_consulting"}

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
# Options: "claude" (metered API) | "claude_code" (subscription) | "gemini" | "codex"
#
# "claude" calls the metered Anthropic API directly (requires ANTHROPIC_API_KEY below).
# No Claude Code CLI login or session-window limit — every stage script (via ai_chat())
# runs independently of any subscription session, and prompt caching is enabled.
AI_PROVIDER = "claude"

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
# are set (e.g. in the GitHub Actions workflow env).
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

# Per-provider model overrides for gemini/codex/claude_code — keyed by provider, each with
# "fast" (stages 1/3) and "quality" (stages 2/5/6) entries. Blank/missing falls back to that
# backend's built-in default (see _DEFAULTS in scripts/utils.py). This is what makes switching
# AI_PROVIDER (or a single tier via FAST_PROVIDER/QUALITY_PROVIDER) to gemini/codex safe to do
# at any time — the right model comes along with the provider instead of being a separate,
# easy-to-forget field.
MODEL_OVERRIDES = {
    # "gemini": {"fast": "gemini-2.0-flash", "quality": "gemini-1.5-pro"},
    # "codex":  {"fast": "gpt-4o-mini",      "quality": "gpt-4o"},
}

# --- API Keys -----------------------------------------------
APIFY_API_TOKEN   = "***REMOVED-APIFY-TOKEN***"   # https://apify.com  (free token)
NOTION_API_KEY    = os.environ.get("NOTION_API_KEY", "")   # set in your env (the integration token; DB is shared & working)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")   # set in your env (metered API key for AI_PROVIDER="claude")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")   # set in your env (required for AI_PROVIDER="gemini")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")   # set in your env (required for AI_PROVIDER="codex")
HUNTER_API_KEY    = os.environ.get("HUNTER_API_KEY", "")   # set in your env (Step 7 Phase 0 spike — Hunter.io email finder/verifier)

# --- Step 7 Phase 0 spike (communications subsystem) ---------
# Apify actor id for LinkedIn job-poster/recruiter discovery (coregent, no li_at cookie needed).
# See scripts/spike_phase0_leads.py and docs/backlog/step-7-communications-subsystem.md.
LEAD_ACTOR = "coregent~linkedin-recruiter-job-poster-finder"

# --- Notion IDs (already created for you) -------------------
NOTION_DB_ID      = "2ac0907e693744698a1c748d37774a07"   # Job Search Tracker

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
