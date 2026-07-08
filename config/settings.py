# ============================================================
#  config/settings.py  —  Fill these in before running
# ============================================================

# --- Your profile -------------------------------------------
YOUR_NAME        = "Krishna Achyuth"
YOUR_EMAIL       = "kachyuth06@example.com"
YOUR_BIO         = "2-line professional bio used in outreach emails" #TODO: write a concise, compelling bio that highlights your experience and value proposition as a Senior Software Engineer.

# --- Job search targets -------------------------------------
TARGET_ROLES     = ["Software Engineer", "Senior Software Engineer", "Backend Engineer", "Full Stack Engineer", "Staff Software Engineer"]  # list of 2-3 roles you're targeting
# Search is always US-wide. Jobs are filtered to US locations post-scrape.
TARGET_COMPANIES = ["Google", "Meta", "Stripe", "Notion", "Figma"]

# --- Company denylist (stage 1) -----------------------------
# Two-layer filter: exact-name list + keyword patterns.
# Both are matched case-insensitively as substrings of the company name.
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
    "BeaconFire Inc.", "Reflexive Concepts", "Qualcomm",
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
# Paste your LinkedIn "li_at" session cookie value here.
# With a Premium session, Apify returns applicant_count, salary ranges,
# and "Top Applicant" signals that anonymous scraping can't see.
# How to get it: browser DevTools → Application → Cookies → linkedin.com → li_at
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

# --- Resume -------------------------------------------------
# Upload your resume as a .txt or .md file and set path here
RESUME_PATH      = "config/resume.txt"
GDRIVE_RESUME_ID = ""    # Optional: Google Drive file ID of master resume
# Base resume .docx used as the source for tailoring (stage 2). The pipeline
# copies this file and applies targeted ATS keyword edits in-place, preserving
# all formatting. Must be a plain Word document (no Jinja2 placeholders needed).
RESUME_TEMPLATE_PATH = "config/Achyuth_Resume.docx"

# --- AI Provider --------------------------------------------
# Choose which LLM powers all pipeline stages
# Options: "claude" (metered API) | "claude_code" (subscription via CLI) | "gemini" | "codex"
#
# "claude_code" routes stage-script calls (run.py: stages 1,2,3,5,6) through the `claude -p`
# CLI, which uses your logged-in Claude Code subscription instead of a metered API key.
# Prerequisite: install the Claude Code CLI and run `claude /login`. No prompt caching on
# this path. NOTE: do NOT export ANTHROPIC_API_KEY as an env var — the CLI would prefer it
# over the subscription. (workflow.py's agentic loop still uses the metered API directly.)
AI_PROVIDER = "claude_code"

# Model overrides — leave blank to use the defaults below
#   claude default      : claude-opus-4-6
#   claude_code default : sonnet  (CLI accepts aliases: haiku | sonnet | opus, or full claude-* ids)
#   gemini default      : gemini-2.0-flash
#   codex  default      : gpt-4o
AI_MODEL_OVERRIDE = "haiku"     # fast/cheap — stages 1, 3
QUALITY_MODEL     = "sonnet"    # strong — stages 2, 5, 6, workflow

# --- API Keys -----------------------------------------------
ANTHROPIC_API_KEY = "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"   # https://console.anthropic.com         (provider: claude)
GEMINI_API_KEY    = ""   # https://aistudio.google.com/apikey    (provider: gemini)
OPENAI_API_KEY    = "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"   # https://platform.openai.com/api-keys  (provider: codex)
APIFY_API_TOKEN   = "apify_api_DcVU8FOcBhj2P95Aaw2HNh2UeWFDhB3C7Ryr"   # https://apify.com  (free token)
NOTION_API_KEY    = "ntn_w28125366012r0VqDA4LehcDJ8OxaJAfiFg8UXjh5iqcF8"   # TEMP-DISABLED (was ntn_w28125366012r0VqDA4LehcDJ8OxaJAfiFg8UXjh5iqcF8) — DB not shared with integration; re-enable after sharing

# --- Notion IDs (already created for you) -------------------
NOTION_DB_ID      = "2ac0907e693744698a1c748d37774a07"   # Job Search Tracker

# --- Supabase (primary data store) --------------------------
SUPABASE_URL      = "https://qgluulgbtdzcreehrcqx.supabase.co"   # https://your-project.supabase.co
SUPABASE_KEY      = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFnbHV1bGdidGR6Y3JlZWhyY3F4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDQxNjAwMCwiZXhwIjoyMDk1OTkyMDAwfQ.nUAAYgNVxa-87FDTshMYleQ2vQMpGmlf5mSNlKzuNi0"   # service_role key — Project Settings > API

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
