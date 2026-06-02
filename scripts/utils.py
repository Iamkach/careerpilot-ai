"""
utils.py — Shared helpers used across all job search scripts
"""
import os, json, sys, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config.settings import *

# ── Default models per provider ─────────────────────────────
_DEFAULTS = {
    "claude": "claude-opus-4-6",
    "gemini": "gemini-2.0-flash",
    "codex":  "gpt-4o",
}

def _active_model() -> str:
    return AI_MODEL_OVERRIDE or _DEFAULTS.get(AI_PROVIDER, _DEFAULTS["claude"])


# ── Provider backends ────────────────────────────────────────

def _chat_claude(prompt: str, system: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {
        "model":      _active_model(),
        "max_tokens": max_tokens,
        "messages":   [{"role": "user", "content": prompt}],
    }
    if system:
        # Cache the system prompt — it's identical across calls within a stage run
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    resp = client.messages.create(**kwargs)
    return resp.content[0].text


def _chat_gemini(prompt: str, system: str, max_tokens: int) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    config = genai.types.GenerationConfig(max_output_tokens=max_tokens)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    model = genai.GenerativeModel(_active_model())
    resp = model.generate_content(full_prompt, generation_config=config)
    return resp.text


def _chat_codex(prompt: str, system: str, max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=_active_model(),
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


# ── Public chat interface ────────────────────────────────────

_BACKENDS = {
    "claude": _chat_claude,
    "gemini": _chat_gemini,
    "codex":  _chat_codex,
}

def ai_chat(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    backend = _BACKENDS.get(AI_PROVIDER)
    if not backend:
        raise ValueError(f"Unknown AI_PROVIDER '{AI_PROVIDER}'. Choose: claude, gemini, codex")
    return backend(prompt, system, max_tokens)

# Alias so all existing stage scripts continue to work without changes
claude_chat = ai_chat


# ── Legacy helper (kept for backward compat) ─────────────────
def get_claude():
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Helpers ──────────────────────────────────────────────────
def today() -> str:
    return datetime.date.today().isoformat()

def load_resume() -> str:
    path = ROOT / RESUME_PATH
    if not path.exists():
        raise FileNotFoundError(f"Resume not found at {RESUME_PATH}. Add it to config/resume.txt")
    return path.read_text()

def ensure_dirs():
    for d in [OUTPUT_DIR, RESUMES_DIR, PREP_GUIDES_DIR]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)

def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── Supabase (primary data store) ────────────────────────────

def _get_db():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Notion mirror (optional — visual tracker UI) ──────────────

def _notion_write_job(job: dict) -> str | None:
    """Create a Notion page mirroring the job. Returns notion_page_id or None."""
    if not NOTION_API_KEY:
        return None
    try:
        from notion_client import Client as NotionClient
        notion = NotionClient(auth=NOTION_API_KEY)
        props = {
            "Job Title":    {"title": [{"text": {"content": job.get("title", "")}}]},
            "Company":      {"rich_text": [{"text": {"content": job.get("company", "")}}]},
            "Job URL":      {"url": job.get("url") or None},
            "Status":       {"select": {"name": "Scraped"}},
            "Date Scraped": {"date": {"start": today()}},
        }
        if job.get("ats_score"):
            props["ATS Match Score"] = {"number": float(job["ats_score"])}
        page = notion.pages.create(parent={"database_id": NOTION_DB_ID}, properties=props)
        return page["id"]
    except Exception:
        return None


# Maps snake_case extra_props keys → Notion property dicts
_EXTRA_TO_NOTION = {
    "tailored_resume_link":    lambda v: {"Tailored Resume Link": {"url": v}},
    "date_applied":            lambda v: {"Date Applied": {"date": {"start": v}}},
    "hiring_manager":          lambda v: {"Hiring Manager": {"rich_text": [{"text": {"content": v}}]}},
    "hiring_manager_linkedin": lambda v: {"Hiring Manager LinkedIn": {"url": v}},
}

def _notion_update(notion_page_id: str, status: str, extra_props: dict = None):
    """Mirror a status update to Notion. No-op if key not set or page_id missing."""
    if not NOTION_API_KEY or not notion_page_id:
        return
    try:
        from notion_client import Client as NotionClient
        notion = NotionClient(auth=NOTION_API_KEY)
        props = {"Status": {"select": {"name": status}}}
        for k, v in (extra_props or {}).items():
            converter = _EXTRA_TO_NOTION.get(k)
            if converter:
                props.update(converter(v))
        notion.pages.update(page_id=notion_page_id, properties=props)
    except Exception:
        pass


# ── Public DB interface ───────────────────────────────────────

def db_find_job_by_url(url: str) -> str | None:
    """Return Supabase job id if URL already exists, else None."""
    res = _get_db().table("jobs").select("id").eq("job_url", url).execute()
    return res.data[0]["id"] if res.data else None


def db_add_job(job: dict) -> str:
    """Insert job into Supabase, mirror to Notion if key set. Returns Supabase id."""
    db = _get_db()
    row = {
        "job_title":       job.get("title", ""),
        "company":         job.get("company", ""),
        "job_url":         job["url"],
        "status":          "Scraped",
        "date_scraped":    today(),
        "ats_match_score": float(job.get("ats_score") or 0),
    }
    res = db.table("jobs").insert(row).execute()
    supabase_id = res.data[0]["id"]

    notion_page_id = _notion_write_job(job)
    if notion_page_id:
        db.table("jobs").update({"notion_page_id": notion_page_id}).eq("id", supabase_id).execute()

    return supabase_id


def db_update_status(job_id: str, status: str, extra_props: dict = None):
    """Update status in Supabase and mirror to Notion."""
    db = _get_db()
    updates = {"status": status}
    if extra_props:
        updates.update(extra_props)
    db.table("jobs").update(updates).eq("id", job_id).execute()

    if NOTION_API_KEY:
        res = db.table("jobs").select("notion_page_id").eq("id", job_id).execute()
        notion_page_id = res.data[0]["notion_page_id"] if res.data else None
        _notion_update(notion_page_id, status, extra_props)


def db_get_ready_to_apply() -> list:
    """Jobs with Status='Resume Tailored' and no date_applied, sorted by score desc."""
    res = (
        _get_db().table("jobs")
        .select("id,job_title,company,job_url,ats_match_score,tailored_resume_link")
        .eq("status", "Resume Tailored")
        .is_("date_applied", "null")
        .order("ats_match_score", desc=True)
        .execute()
    )
    return [
        {
            "page_id":     r["id"],
            "title":       r["job_title"],
            "company":     r["company"],
            "url":         r["job_url"],
            "ats":         r["ats_match_score"] or 0,
            "resume_link": r["tailored_resume_link"] or "",
        }
        for r in res.data
    ]


def db_get_jobs(status: str, min_score: float = 0) -> list:
    """Jobs filtered by status and min ATS score, sorted by score desc."""
    res = (
        _get_db().table("jobs")
        .select("id,job_title,company,job_url,ats_match_score,tailored_resume_link")
        .eq("status", status)
        .gte("ats_match_score", min_score)
        .order("ats_match_score", desc=True)
        .execute()
    )
    return [
        {
            "page_id":     r["id"],
            "title":       r["job_title"],
            "company":     r["company"],
            "url":         r["job_url"],
            "ats_score":   r["ats_match_score"] or 0,
            "resume_link": r["tailored_resume_link"] or "",
        }
        for r in res.data
    ]


def db_get_job_by_company(company: str) -> dict | None:
    """Return full job dict for first match on company name (case-insensitive), or None."""
    res = (
        _get_db().table("jobs")
        .select("id,job_title,company,job_url,hiring_manager,hiring_manager_linkedin")
        .ilike("company", f"%{company}%")
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    r = res.data[0]
    return {
        "page_id": r["id"],
        "title":   r["job_title"],
        "company": r["company"],
        "url":     r["job_url"],
        "hm":      r["hiring_manager"] or "",
        "hm_li":   r["hiring_manager_linkedin"] or "",
    }
