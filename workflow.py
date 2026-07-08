#!/usr/bin/env python3
"""
workflow.py — Claude Agent SDK Workflow for Job Search Pipeline
──────────────────────────────────────────────────────────────
A Claude-native workflow on the Claude Code subscription (claude-agent-sdk): the model
orchestrates all 6 stages via in-process tools (exposed as the `jobpipe` MCP server) with
streaming output. No metered API key — auth is the logged-in subscription.

Usage:
  python workflow.py                                          # Morning pipeline (stages 1-4)
  python workflow.py --task scrape                           # Stage 1: scrape LinkedIn
  python workflow.py --task tailor --min-score 65            # Stage 2: tailor resumes
  python workflow.py --task outreach --company "Stripe"      # Stage 3: cold outreach
  python workflow.py --task outreach --company "Google" --contact "Jane Doe" --contact-role "PM"
  python workflow.py --task digest --send                    # Stage 4: email digest
  python workflow.py --task interview --company "Meta" --role "Senior PM"
  python workflow.py --task negotiate --company "Stripe" --role "PM" --offer 185000
"""

import sys, os, json, asyncio, argparse
from pathlib import Path
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Force subscription auth: the Agent SDK spawns the `claude` CLI, which uses the logged-in
# subscription only when ANTHROPIC_API_KEY is absent from the environment.
os.environ.pop("ANTHROPIC_API_KEY", None)

from claude_agent_sdk import (
    query, ClaudeAgentOptions, tool, create_sdk_mcp_server,
    AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
)
from config.settings import (
    APIFY_API_TOKEN,
    NOTION_API_KEY, NOTION_DB_ID,
    TARGET_ROLES,
    RESUME_PATH, OUTPUT_DIR, RESUMES_DIR, PREP_GUIDES_DIR,
    YOUR_NAME, YOUR_EMAIL, YOUR_BIO,
    GMAIL_CREDENTIALS_PATH, DIGEST_RECIPIENT_EMAIL,
    AI_MODEL_OVERRIDE,
    QUALITY_MODEL,
)


# ── Tool implementations ──────────────────────────────────────────────
# These are the "hands" — they perform side effects.
# Claude is the "brain" that decides when to call them.

def _impl_scrape_linkedin_jobs(role: str, city: str, max_results: int = 10) -> dict:
    import requests, time
    APIFY_BASE = "https://api.apify.com/v2"
    APIFY_ACTOR = "curious_coder~linkedin-jobs-scraper"

    run_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/runs"
    # Actor schema: `urls` (array of LinkedIn search/job URLs) + `count` (min 10).
    search_url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={requests.utils.quote(role)}"
        f"&location={requests.utils.quote(city)}"
        f"&f_TPR=r86400"
    )
    payload = {
        "urls": [search_url],
        "count": max(max_results, 10),
        "scrapeCompany": False,
    }
    r = requests.post(run_url, json=payload, params={"token": APIFY_API_TOKEN})
    r.raise_for_status()
    run_id = r.json()["data"]["id"]

    for _ in range(30):
        time.sleep(10)
        status_r = requests.get(
            f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": APIFY_API_TOKEN}
        )
        status = status_r.json()["data"]["status"]
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED"):
            return {"error": f"Apify run {status}", "jobs": [], "count": 0}

    dataset_id = status_r.json()["data"]["defaultDatasetId"]
    items_r = requests.get(
        f"{APIFY_BASE}/datasets/{dataset_id}/items", params={"token": APIFY_API_TOKEN}
    )
    items = items_r.json()

    # curious_coder actor fields: link / title / companyName / descriptionText.
    # Keep legacy fallbacks so older/alternate actors still work.
    jobs = [
        {
            "title":       item.get("title") or item.get("positionName") or role,
            "company":     item.get("companyName") or item.get("company") or "",
            "url":         item.get("link") or item.get("jobUrl") or item.get("url") or "",
            "location":    item.get("location") or item.get("formattedLocation") or "",
            "description": (item.get("descriptionText") or item.get("descriptionHtml")
                            or item.get("description") or item.get("jobDescription") or "")[:3000],
        }
        for item in items
        if item.get("link") or item.get("jobUrl") or item.get("url")
    ]
    return {"jobs": jobs, "count": len(jobs)}


def _impl_check_job_in_db(url: str) -> dict:
    from scripts.utils import db_find_job_by_url
    job_id = db_find_job_by_url(url)
    return {"exists": bool(job_id), "page_id": job_id}


def _impl_add_job_to_db(
    title: str, company: str, url: str, ats_score: float,
    location: str = "", missing_keywords: list = None
) -> dict:
    from scripts.utils import db_add_job
    job_id = db_add_job({
        "title": title, "company": company, "url": url,
        "location": location, "ats_score": ats_score,
    })
    return {"page_id": job_id, "success": True}


def _impl_get_jobs(status: str, min_score: float = 0) -> dict:
    from scripts.utils import db_get_jobs
    jobs = db_get_jobs(status=status, min_score=min_score)
    return {"jobs": jobs, "count": len(jobs)}


def _impl_get_ready_to_apply() -> dict:
    from scripts.utils import db_get_ready_to_apply
    jobs = db_get_ready_to_apply()
    # Normalize "ats" key to "ats_score" for workflow.py callers
    for job in jobs:
        job.setdefault("ats_score", job.get("ats", 0))
    return {"jobs": jobs, "count": len(jobs)}


def _impl_fetch_job_description(url: str) -> dict:
    """Fetch raw page content from a job URL; Claude extracts the JD text."""
    if not url:
        return {"text": "", "error": "No URL provided"}
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (compatible; job-search-bot/1.0)"}
        r = requests.get(url, timeout=15, headers=headers)
        # Strip HTML tags via basic regex to reduce token count
        import re
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return {"text": text[:6000], "url": url}
    except Exception as e:
        return {"text": "", "error": str(e)}


def _impl_save_tailored_resume(
    content: str, company: str, role: str, page_id: str
) -> dict:
    from scripts.utils import db_update_status
    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").strip()
    filename = (
        f"{date.today().isoformat()}_{safe(company)}_{safe(role)}.txt"
        .replace(" ", "_")
    )
    path = ROOT / RESUMES_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    db_update_status(page_id, "Resume Tailored", {
        "tailored_resume_link": f"file://{path.resolve()}",
        "date_applied": date.today().isoformat(),
    })
    return {"file_path": str(path), "success": True}


def _impl_save_outreach_email(content: str, company: str, contact: str = "") -> dict:
    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " _-").strip()
    suffix = f"_{safe(contact)}" if contact else ""
    filename = (
        f"{date.today().isoformat()}_{safe(company)}{suffix}_outreach.txt"
        .replace(" ", "_")
    )
    path = ROOT / OUTPUT_DIR / "outreach" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"file_path": str(path), "success": True}


def _impl_save_html_file(content: str, filename: str, subdirectory: str = "") -> dict:
    if subdirectory:
        out_dir = ROOT / OUTPUT_DIR / subdirectory
    else:
        out_dir = ROOT / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = filename if filename.endswith(".html") else f"{filename}.html"
    path = out_dir / fname
    path.write_text(content, encoding="utf-8")
    return {"file_path": str(path), "success": True}


def _impl_sync_disregard() -> dict:
    """No-op kept for tool compatibility: Notion is the single source of truth, so
    'Reviewed' status is read directly from Notion — no sync step is needed."""
    return {"synced": 0, "success": True}


def _impl_update_status(
    page_id: str, status: str, tailored_resume_link: str = ""
) -> dict:
    from scripts.utils import db_update_status
    extra = {}
    if tailored_resume_link:
        extra["tailored_resume_link"] = tailored_resume_link
    db_update_status(page_id, status, extra or None)
    return {"success": True}


def _impl_send_digest_email(html_content: str) -> dict:
    """Send HTML digest via Gmail OAuth."""
    try:
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(GMAIL_CREDENTIALS_PATH)
        service = build("gmail", "v1", credentials=creds)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Job applications ready — {date.today().isoformat()}"
        msg["From"] = YOUR_EMAIL
        msg["To"] = DIGEST_RECIPIENT_EMAIL
        msg.attach(MIMEText(html_content, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "sent_to": DIGEST_RECIPIENT_EMAIL}
    except ImportError:
        return {"success": False, "error": "pip install google-auth google-auth-oauthlib google-api-python-client"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool dispatch ─────────────────────────────────────────────────────

_TOOL_IMPL = {
    "scrape_linkedin_jobs":  _impl_scrape_linkedin_jobs,
    "check_job_in_db":       _impl_check_job_in_db,
    "add_job_to_db":         _impl_add_job_to_db,
    "get_jobs":              _impl_get_jobs,
    "get_ready_to_apply":    _impl_get_ready_to_apply,
    "fetch_job_description": _impl_fetch_job_description,
    "save_tailored_resume":  _impl_save_tailored_resume,
    "save_outreach_email":   _impl_save_outreach_email,
    "save_html_file":        _impl_save_html_file,
    "update_status":         _impl_update_status,
    "send_digest_email":     _impl_send_digest_email,
    "sync_disregard":        _impl_sync_disregard,
}


def _print_tool_outcome(result: dict):
    """Brief, human-readable outcome line for a tool result (mirrors the old loop)."""
    if "error" in result:
        print(f"     ✗ {result['error']}")
    elif "count" in result:
        print(f"     → {result['count']} item(s)")
    elif result.get("success"):
        fp = result.get("file_path", "")
        print(f"     ✓{' ' + fp if fp else ''}")
    elif result.get("exists") is not None:
        print(f"     → exists={result['exists']}")


def _make_tool(name: str, description: str, schema: dict, impl):
    """Wrap an existing sync `_impl_*` function (+ its JSON schema) as an SDK in-process
    tool. The blocking impl runs in a thread so it doesn't stall the event loop."""
    @tool(name, description, schema)
    async def _t(args):
        try:
            result = await asyncio.to_thread(impl, **args)
        except Exception as e:
            result = {"error": str(e)}
        _print_tool_outcome(result)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    return _t


# ── Tool schemas for Claude ───────────────────────────────────────────

TOOLS = [
    {
        "name": "scrape_linkedin_jobs",
        "description": (
            "Scrape recent LinkedIn job postings via Apify for a given role + city. "
            "Call this for each target role. Returns normalized jobs with title, company, url, description."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role":        {"type": "string", "description": "Job title to search"},
                "city":        {"type": "string", "description": "City and state"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["role", "city"],
        },
    },
    {
        "name": "check_job_in_db",
        "description": (
            "Check if a job URL already exists in the database. "
            "Call before add_job_to_db to prevent duplicates. "
            "Returns {exists: bool, page_id: str|null}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "add_job_to_db",
        "description": (
            "Add a new job to the database with Status='Scraped'. Also mirrors to Notion tracker. "
            "Only call after check_job_in_db confirms it doesn't exist. "
            "Returns {page_id, success}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title":            {"type": "string"},
                "company":          {"type": "string"},
                "url":              {"type": "string"},
                "location":         {"type": "string", "description": "Job location (city/state or Remote)"},
                "ats_score":        {"type": "number", "description": "ATS keyword match score 0-100"},
                "missing_keywords": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "company", "url", "ats_score"],
        },
    },
    {
        "name": "get_jobs",
        "description": (
            "Fetch jobs from the database filtered by status and minimum ATS score. "
            "Returns sorted list of jobs with page_id, title, company, url, ats_score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "Scraped", "Disregard", "Resume Tailored", "Applied",
                        "Outreach Sent", "Interview Scheduled", "Offer Received",
                    ],
                },
                "min_score": {"type": "number", "default": 0},
            },
            "required": ["status"],
        },
    },
    {
        "name": "get_ready_to_apply",
        "description": (
            "Get all jobs with Status='Resume Tailored' and no Date Applied. "
            "Use this to build the morning digest or outreach list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "fetch_job_description",
        "description": (
            "Fetch the raw text of a job posting URL so you can extract the job description. "
            "Returns page text (first 6000 chars). You extract the actual JD from this text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "save_tailored_resume",
        "description": (
            "Write a tailored resume to output/resumes/ and update the job status to "
            "'Resume Tailored' in the database (+ Notion mirror). Call after rewriting the resume."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Full tailored resume text"},
                "company": {"type": "string"},
                "role":    {"type": "string"},
                "page_id": {"type": "string", "description": "Notion page ID to update"},
            },
            "required": ["content", "company", "role", "page_id"],
        },
    },
    {
        "name": "save_outreach_email",
        "description": (
            "Write a drafted outreach email to output/outreach/ as a .txt file. "
            "Include subject line and body in content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Full email content including subject"},
                "company": {"type": "string"},
                "contact": {"type": "string", "default": "", "description": "Contact name if warm referral"},
            },
            "required": ["content", "company"],
        },
    },
    {
        "name": "save_html_file",
        "description": (
            "Write HTML content to a file. Use for digests (output/), "
            "prep guides (subdirectory='prep_guides'), and negotiation briefs (output/)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content":      {"type": "string", "description": "Full HTML document"},
                "filename":     {"type": "string", "description": "Filename without .html extension"},
                "subdirectory": {"type": "string", "default": "", "description": "Subdirectory within output/"},
            },
            "required": ["content", "filename"],
        },
    },
    {
        "name": "update_status",
        "description": "Update a job's status field in the database (+ Notion mirror).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id":              {"type": "string"},
                "status":               {"type": "string"},
                "tailored_resume_link": {"type": "string", "default": ""},
            },
            "required": ["page_id", "status"],
        },
    },
    {
        "name": "send_digest_email",
        "description": (
            "Send an HTML digest email to the configured address via Gmail OAuth. "
            "Only call when --send flag was requested."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "html_content": {"type": "string", "description": "Full HTML email body"},
            },
            "required": ["html_content"],
        },
    },
    {
        "name": "sync_disregard",
        "description": (
            "Deprecated no-op (Notion is the single source of truth — 'Reviewed' status is read "
            "directly from Notion). Safe to skip; kept only for backward compatibility."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ── SDK in-process tool server ────────────────────────────────────────
# Wrap each schema (TOOLS) + impl (_TOOL_IMPL) pair into an SDK tool and expose them as a
# single in-process MCP server. Tool names the model may call: mcp__jobpipe__<name>.

_SDK_TOOLS = [
    _make_tool(t["name"], t["description"], t["input_schema"], _TOOL_IMPL[t["name"]])
    for t in TOOLS
]
_SERVER  = create_sdk_mcp_server(name="jobpipe", version="1.0.0", tools=_SDK_TOOLS)
_ALLOWED = [f"mcp__jobpipe__{t['name']}" for t in TOOLS]


# ── Task prompts ──────────────────────────────────────────────────────

def _task_morning(args) -> str:
    today = date.today().isoformat()
    targets = ", ".join(f'"{r}"' for r in TARGET_ROLES)
    notion_url = f"https://www.notion.so/{NOTION_DB_ID.replace('-', '')}"
    return f"""Today is {today}. Run the morning scrape and send a review digest.

STAGE 1 — SCRAPE
For each target role ({targets}), scrape LinkedIn across United States.
For each result:
  1. Call check_job_in_db — skip if already tracked
  2. Score the job against my resume (ATS keyword match, 0-100) and note missing keywords
  3. Call add_job_to_db with the score
After all roles: summarize total added / skipped.

STAGE 2 — REVIEW DIGEST
  1. Call get_jobs(status="Scraped") to get all newly scraped jobs
  2. Build a clean HTML review digest:
     — Header: "New Jobs Scraped — {today} — Review Required"
     — Yellow notice box: "Open Notion and set Status = Reviewed on jobs to apply, then run: python run.py --evaluate"
     — Table sorted by ATS score descending: Company | Role | Location | ATS (with 🔥✅🟡⚪ badge) | Job URL
     — Notion tracker link at the bottom: {notion_url}
     — Clean sans-serif CSS, max-width 720px
  3. Save as review_digest_{today} (no subdirectory) using save_html_file
  4. Print a plain-text summary too

This is SCRAPE ONLY — do NOT tailor any resumes. The user will review the digest,
mark good jobs as Reviewed in Notion, then run --evaluate to trigger tailoring.

Give a brief status update between each stage."""


def _task_scrape(args) -> str:
    today = date.today().isoformat()
    targets = ", ".join(f'"{r}"' for r in TARGET_ROLES)
    return f"""Today is {today}. Run Stage 1 — Scrape LinkedIn jobs.

For each target role ({targets}):
  1. Scrape LinkedIn across United States
  2. For each result, check_job_in_db — skip duplicates
  3. Score each new job against my resume (ATS 0-100, list top 3 missing keywords)
  4. Call add_job_to_db

Summarize: how many added, how many skipped, top-scoring jobs."""


def _task_tailor(args) -> str:
    today = date.today().isoformat()
    min_score = getattr(args, "min_score", 0)
    return f"""Today is {today}. Run Stage 2 — Tailor resumes.

Get all "Scraped" jobs from the database with min_score={min_score}.
Process jobs ONE AT A TIME — fully tailor and save a single resume before
starting the next. Do NOT emit multiple save_tailored_resume calls in one
response (a full resume per call overflows the output budget).
For each job:
  1. fetch_job_description from the job URL
  2. Extract the job description text from the fetched HTML
  3. Rewrite my resume for this specific JD:
     — Identify top ATS keywords the JD uses that my resume is missing
     — Rewrite bullet points to naturally incorporate them
     — Preserve the structure, length, and factual accuracy — do NOT invent experience
  4. save_tailored_resume (this also updates Notion status to "Resume Tailored")

Summarize: how many resumes tailored, which companies."""


def _task_evaluate(args) -> str:
    today = date.today().isoformat()
    min_score = getattr(args, "min_score", 0)
    return f"""Today is {today}. The user has reviewed the scraped jobs in Notion and marked good ones as Reviewed.
Now run the evaluate pipeline: tailor → outreach → ready digest.

STEP 1 — TAILOR
Get all "Reviewed" jobs (min_score={min_score}) directly from Notion.
Process jobs ONE AT A TIME — fully tailor and save a single resume before starting the next.
For each job:
  1. fetch_job_description from the job URL
  2. Extract the job description text
  3. Rewrite my resume for this specific JD:
     — Identify top ATS keywords the JD uses that my resume is missing
     — Rewrite bullet points to naturally incorporate them
     — Preserve structure, length, and factual accuracy — do NOT invent experience
  4. save_tailored_resume (updates status to "Resume Tailored" automatically)

STEP 2 — OUTREACH
For each job just tailored, draft a cold outreach email and save with save_outreach_email.

STEP 3 — READY DIGEST
  1. Call get_ready_to_apply to get all tailored jobs
  2. Build a clean HTML digest:
     — Header: "Job Applications Ready — {today}"
     — Table sorted by ATS score: Company | Role | ATS | Resume | Action label
     — Action labels: 🔥 ≥80 apply today, ✅ ≥60 apply + outreach, 🟡 ≥40 apply, ⚪ lower priority
  3. Save as digest_{today} using save_html_file
  4. Print plain-text summary

Summarize: how many tailored, how many reviewed, how many in ready digest."""


def _task_outreach(args) -> str:
    today = date.today().isoformat()
    company = getattr(args, "company", None)
    contact = getattr(args, "contact", None)
    contact_role = getattr(args, "contact_role", "")

    company_filter = f'Filter to jobs at "{company}" only.' if company else "Draft for all ready-to-apply jobs."

    if contact:
        return f"""Today is {today}. Draft a warm referral outreach message. {company_filter}

Contact: {contact}{f" ({contact_role})" if contact_role else ""}
My background: {YOUR_BIO}

For each matching job, write a warm, human, non-transactional LinkedIn message:
  — 3-4 sentences max
  — Reference something specific and genuine about the company or role
  — End with a low-friction ask (happy to share my resume / grab a quick call)
  — No filler phrases like "I hope this finds you well"

Format: Subject (if email) then body. Save each with save_outreach_email."""
    else:
        return f"""Today is {today}. Draft cold outreach emails. {company_filter}

My background: {YOUR_BIO}

For each matching job, write a tight cold email (under 100 words):
  — Subject line that stands out
  — Open with something specific to their work or company (not generic flattery)
  — One sentence on my relevant background
  — One clear, low-pressure CTA
  — Sign off as {YOUR_NAME}

Save each with save_outreach_email. Summarize which emails were saved."""


def _task_digest(args) -> str:
    today = date.today().isoformat()
    send = getattr(args, "send", False)
    send_line = f"\nAfter saving, call send_digest_email with the HTML to email it to {YOUR_EMAIL}." if send else ""
    return f"""Today is {today}. Generate the morning digest.

  1. Call get_ready_to_apply
  2. Build a polished HTML digest:
     — Header: "Job Applications Ready — {date.today().strftime('%B %d, %Y')}"
     — Summary line: N resumes tailored and ready
     — Table sorted by ATS score descending: Company | Role | ATS | Resume | Action
     — Action labels: 🔥 ≥80 (apply today), ✅ ≥60 (apply + outreach), 🟡 ≥40 (apply), ⚪ <40
     — Footer with link to Notion tracker
     — Clean sans-serif CSS, max-width 720px, subtle row hover
  3. Save as digest_{today} with save_html_file{send_line}

Also print a plain-text version to the terminal. Report how many jobs are in the digest."""


def _task_interview(args) -> str:
    today = date.today().isoformat()
    company = getattr(args, "company", "the company")
    role = getattr(args, "role", "the role")
    location = getattr(args, "location", None) or "United States"
    jd_file = getattr(args, "jd_file", "")
    hm_linkedin = getattr(args, "hm_linkedin", "")
    extras = []
    if jd_file:
        extras.append(f"Job description file: {jd_file}")
    if hm_linkedin:
        extras.append(f"Hiring manager LinkedIn: {hm_linkedin}")
    extras_str = "\n".join(extras) if extras else ""

    return f"""Today is {today}. Generate an interview prep guide.

Company: {company}
Role: {role}
{extras_str}

Build a comprehensive HTML prep guide and save it as a file in subdirectory="prep_guides".
Filename: {company.replace(' ', '_')}_{today}_prep

Include:
  1. Company overview (what they do, recent news, business model)
  2. Role analysis (what success looks like in 90 days)
  3. 12-15 likely interview questions (mix of behavioral + technical for this role)
  4. STAR story frameworks drawn from my actual resume for the top 5 questions
  5. 6-8 thoughtful questions to ask the interviewer
  6. Salary benchmarks for {role} in {location} (base + total comp ranges)

Make it scannable: use headers, bullet points, and clear sections. Good HTML styling."""


def _task_negotiate(args) -> str:
    today = date.today().isoformat()
    company = getattr(args, "company", "the company")
    role = getattr(args, "role", "the role")
    offer = getattr(args, "offer", 0)
    location = getattr(args, "location", None) or "United States"
    offer_str = f"${offer:,.0f}" if offer else "not yet disclosed"

    return f"""Today is {today}. Generate a salary negotiation brief.

Company: {company}
Role: {role}
Current offer: {offer_str}

Build an HTML negotiation brief and save it with save_html_file.
Filename: {company.replace(' ', '_')}_{today}_negotiation

Include:
  1. Market salary data for {role} in {location} (P25 / P50 / P75 / P90 ranges)
  2. Total compensation breakdown guide (base, equity, bonus, 401k, benefits)
  3. Negotiation strategy — opening position, BATNA, walk-away point
  4. Word-for-word scripts: email counter-offer and phone call opener
  5. Specific asks beyond base: signing bonus, extra vacation, remote flexibility
  6. Red flags to watch for in the offer letter

Make it actionable. Good HTML styling with clear sections."""


_TASK_BUILDERS = {
    "morning":   _task_morning,
    "scrape":    _task_scrape,
    "tailor":    _task_tailor,
    "evaluate":  _task_evaluate,
    "outreach":  _task_outreach,
    "digest":    _task_digest,
    "interview": _task_interview,
    "negotiate": _task_negotiate,
}


# ── System prompt with prompt caching ────────────────────────────────
# The system prompt is split into blocks so we can cache the large, stable
# resume separately. The API caches by prefix, so tools + system must be
# byte-identical across calls for the cache to hit.

def _build_system(resume: str) -> list:
    core = f"""You are an AI job search assistant for {YOUR_NAME} ({YOUR_EMAIL}).
You orchestrate a 6-stage job search pipeline by calling the provided tools.
Claude is the brain — you score jobs, write content, make decisions.
Tools are the hands — they do file I/O, API calls, and Notion updates.

Pipeline overview:
  Stage 1 (scrape)    — Scrape LinkedIn → score vs resume → add to Notion
  Stage 2 (tailor)    — Fetch JD → rewrite resume → save → update Notion
  Stage 3 (outreach)  — Draft cold/warm emails → save to output/outreach/
  Stage 4 (digest)    — Build HTML digest of tailored jobs
  Stage 5 (interview) — Generate HTML interview prep guide
  Stage 6 (negotiate) — Generate HTML salary negotiation brief

Rules:
  — Always call check_job_in_db before add_job_to_db (prevent duplicates)
  — ATS scoring: keyword overlap between JD and resume, 0-100
  — Resume tailoring: surface matching skills, add missing keywords naturally — never invent experience
  — Output filenames always include today's date for tracking
  — After major milestones, give a concise status update"""

    profile = f"""Candidate profile:
  Name:         {YOUR_NAME}
  Email:        {YOUR_EMAIL}
  Bio:          {YOUR_BIO}
  Target roles: {', '.join(TARGET_ROLES)}
  Target location: United States (nationwide)
  Notion DB:    https://www.notion.so/{NOTION_DB_ID.replace('-', '')}"""

    resume_block = f"""My base resume — use this as the foundation for all tailoring:

<resume>
{resume}
</resume>"""

    return [
        {"type": "text", "text": core},
        {"type": "text", "text": profile},
        # Resume is the largest block and doesn't change between calls — cache it.
        # The cache prefix includes: tools + core + profile + resume.
        # Volatile content (the task prompt) goes in messages[], not system.
        {"type": "text", "text": resume_block, "cache_control": {"type": "ephemeral"}},
    ]


# ── Agentic loop (Agent SDK over the Claude Code subscription) ─────────

_MAX_TURNS = 60  # generous cap for the morning pipeline (many jobs × many tools)


async def _run(task_prompt: str, system_str: str):
    """Drive one task to completion via the SDK's native agentic loop. The SDK runs the
    full tool loop internally; we just stream text, echo tool calls, and report usage."""
    opts = ClaudeAgentOptions(
        system_prompt=system_str,
        model=QUALITY_MODEL or AI_MODEL_OVERRIDE or "sonnet",
        mcp_servers={"jobpipe": _SERVER},
        allowed_tools=_ALLOWED,        # pre-approve only our jobpipe tools
        permission_mode="dontAsk",     # deny anything not pre-approved (no built-ins, no prompts)
        strict_mcp_config=True,        # ignore any user/project MCP servers (Notion, etc.)
        setting_sources=[],            # don't load project CLAUDE.md/settings into the prompt
        max_turns=_MAX_TURNS,
    )

    async for msg in query(prompt=task_prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text, end="", flush=True)
                elif isinstance(block, ToolUseBlock):
                    preview = ", ".join(f"{k}={repr(v)[:50]}" for k, v in (block.input or {}).items())
                    # Strip the mcp__jobpipe__ prefix for readability
                    short = block.name.split("__")[-1]
                    print(f"\n  ⚙  {short}({preview})")
        elif isinstance(msg, ResultMessage):
            print(f"\n\n{'─' * 40}")
            if msg.subtype != "success":
                print(f"  [!] Ended: {msg.subtype}")
            cost = getattr(msg, "total_cost_usd", None)
            usage = getattr(msg, "usage", None)
            if usage:
                print(f"  Usage: {usage}")
            if cost is not None:
                print(f"  Subscription cost-equivalent: ${cost:.4f}")
            print(f"  Done. ({msg.num_turns} turn(s))" if getattr(msg, "num_turns", None) else "  Done.")
            print(f"{'─' * 40}\n")


def run_workflow(task: str, args):
    resume_path = ROOT / RESUME_PATH
    if not resume_path.exists():
        print(f"✗ Resume not found at {RESUME_PATH}. Add your resume to config/resume.txt first.")
        sys.exit(1)
    resume = resume_path.read_text(encoding="utf-8")

    # cache_control is dropped here (unsupported over the subscription); join blocks to a string.
    system_str = "\n\n".join(b["text"] for b in _build_system(resume))
    task_prompt = _TASK_BUILDERS[task](args)

    banner = f"Claude Workflow — {task.upper()}"
    print(f"\n{'─' * len(banner)}")
    print(banner)
    print(f"{'─' * len(banner)}\n")

    asyncio.run(_run(task_prompt, system_str))


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Job Search — Claude Agent SDK Workflow (subscription)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--task", default="morning",
        choices=["morning", "scrape", "tailor", "evaluate", "outreach", "digest", "interview", "negotiate"],
        help="Which task to run (default: morning = scrape + review digest; evaluate = tailor + outreach + ready digest)",
    )
    parser.add_argument("--min-score",    type=int,   default=0,  dest="min_score",
                        help="Minimum ATS score for tailor stage")
    parser.add_argument("--company",      type=str,   default=None)
    parser.add_argument("--role",         type=str,   default="")
    parser.add_argument("--contact",      type=str,   default=None,
                        help="Contact name for warm referral outreach")
    parser.add_argument("--contact-role", type=str,   default="", dest="contact_role")
    parser.add_argument("--jd-file",      type=str,   default="", dest="jd_file",
                        help="Path to job description file for interview prep")
    parser.add_argument("--hm-linkedin",  type=str,   default="", dest="hm_linkedin",
                        help="Hiring manager LinkedIn URL for interview prep")
    parser.add_argument("--offer",        type=float, default=0,
                        help="Current offer amount for negotiation brief")
    parser.add_argument("--send",         action="store_true",
                        help="Send digest via Gmail (requires OAuth credentials)")
    args = parser.parse_args()
    run_workflow(args.task, args)


if __name__ == "__main__":
    main()
