# ============================================================
#  config/settings.py  —  Fill these in before running
# ============================================================

# --- Your profile -------------------------------------------
YOUR_NAME        = "Krishna Achyuth"
YOUR_EMAIL       = "kachyuth06@example.com"
YOUR_BIO         = "2-line professional bio used in outreach emails" #TODO: write a concise, compelling bio that highlights your experience and value proposition as a Senior Software Engineer.

# --- Job search targets -------------------------------------
TARGET_ROLES     = ["Software Engineer", "Senior Software Engineer", "Backend Engineer", "Full Stack Engineer", "Staff Software Engineer"]  # list of 2-3 roles you're targeting
TARGET_CITY      = "Dallas, TX"          # or "Remote" — leave blank "" for US-wide search
TARGET_COMPANIES = ["Google", "Meta", "Stripe", "Notion", "Figma"]

# --- Company denylist (stage 1) -----------------------------
# Skip jobs from these companies (IT-services / consulting / staffing firms —
# product-based companies only). Matched case-insensitively as a substring of
# the company name, so "Tata" also catches "Tata Consultancy Services".
# Grow this list over time as you spot more to exclude.
SKIP_COMPANIES = [
    # Consulting / IT services
    "Accenture", "Deloitte", "Cognizant", "Tata Consultancy", "TCS", "Infosys",
    "Wipro", "Capgemini", "HCL", "Tech Mahindra", "NTT DATA", "Hexaware",
    "Mphasis", "LTIMindtree", "Genpact", "DXC", "Birlasoft", "Coforge",
    # Staffing / recruiting / job reposters
    "Jobs via Dice", "Dice", "Robert Half", "TalentAlly", "Mastech",
    "Compunnel", "Lorven", "VBeyond", "InfoVision", "Bright Vision",
    "Simpalm", "hackajob", "Insight Global", "TEKsystems", "Randstad",
    "Kforce", "CyberCoders", "Apex Systems", "Collabera", "Diverse Lynx",
]

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
# Word template used to render tailored resumes (stage 2). Must contain the
# docxtpl/Jinja2 placeholders documented in scripts/render_docx.py.
RESUME_TEMPLATE_PATH = "config/resume_template.docx"

# --- AI Provider --------------------------------------------
# Choose which LLM powers all pipeline stages
# Options: "claude" | "gemini" | "codex"
AI_PROVIDER = "claude"

# Model overrides — leave blank to use the defaults below
#   claude default : claude-opus-4-6
#   gemini default : gemini-2.0-flash
#   codex  default : gpt-4o
AI_MODEL_OVERRIDE = "claude-haiku-4-5-20251001"   # fast/cheap — stages 1, 3
QUALITY_MODEL     = "claude-sonnet-4-6"            # strong — stages 2, 5, 6, workflow

# --- API Keys -----------------------------------------------
ANTHROPIC_API_KEY = "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"   # https://console.anthropic.com         (provider: claude)
GEMINI_API_KEY    = ""   # https://aistudio.google.com/apikey    (provider: gemini)
OPENAI_API_KEY    = ""   # https://platform.openai.com/api-keys  (provider: codex)
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

# --- Output dirs --------------------------------------------
OUTPUT_DIR        = "output"
RESUMES_DIR       = "output/resumes"
PREP_GUIDES_DIR   = "output/prep_guides"
