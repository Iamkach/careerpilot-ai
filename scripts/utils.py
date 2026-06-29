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
    "claude":      "claude-opus-4-6",
    "claude_code": "sonnet",
    "gemini":      "gemini-2.0-flash",
    "codex":       "gpt-4o",
}

def _active_model() -> str:
    return AI_MODEL_OVERRIDE or _DEFAULTS.get(AI_PROVIDER, _DEFAULTS["claude"])


# ── Provider backends ────────────────────────────────────────

def _resolve_model(quality: bool) -> str:
    if quality:
        return QUALITY_MODEL or _active_model()
    return _active_model()


def _is_reasoning_model(model: str) -> bool:
    """OpenAI gpt-5 / o-series models use `max_completion_tokens` and reject
    the legacy `max_tokens` param."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _chat_claude(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {
        "model":      _resolve_model(quality),
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


def _find_claude_cli() -> str:
    """Locate the Claude Code CLI executable, robust to Windows .cmd/.exe shims."""
    import shutil
    for name in ("claude", "claude.cmd", "claude.exe"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        "Claude Code CLI not found on PATH. Install it and run `claude /login` so the "
        "`claude_code` provider can use your subscription. (Looked for: claude, claude.cmd, claude.exe)"
    )


def _chat_claude_code(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    """Route a single prompt->text call through the `claude -p` CLI, which uses the
    logged-in Claude Code subscription (no metered API key). The user `prompt` is passed
    via stdin to avoid the Windows command-line length limit; the system prompt (which can
    be large for stages 2/5) is written to a temp file and passed via --system-prompt-file.
    Note: prompt caching is not available over this path; `max_tokens` has no CLI knob."""
    import subprocess, tempfile

    cli = _find_claude_cli()
    cmd = [
        cli, "-p",
        "--output-format", "json",
        "--model", _resolve_model(quality),
        "--max-turns", "1",
        "--tools", "",
    ]

    sys_file = None
    try:
        if system:
            sys_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", encoding="utf-8", delete=False
            )
            sys_file.write(system)
            sys_file.close()
            cmd += ["--system-prompt-file", sys_file.name]

        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
            )

        out = proc.stdout.strip()
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return out  # not the expected envelope — hand back raw text
        return data.get("result", out) if isinstance(data, dict) else out
    finally:
        if sys_file is not None:
            try:
                os.unlink(sys_file.name)
            except OSError:
                pass


def _chat_gemini(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    config = genai.types.GenerationConfig(max_output_tokens=max_tokens)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    model = genai.GenerativeModel(_resolve_model(quality))
    resp = model.generate_content(full_prompt, generation_config=config)
    return resp.text


def _chat_codex(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    model = _resolve_model(quality)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    # gpt-5 / reasoning models reject `max_tokens` and require `max_completion_tokens`.
    token_key = "max_completion_tokens" if _is_reasoning_model(model) else "max_tokens"
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        **{token_key: max_tokens},
    )
    return resp.choices[0].message.content


# ── Public chat interface ────────────────────────────────────

_BACKENDS = {
    "claude":      _chat_claude,
    "claude_code": _chat_claude_code,
    "gemini":      _chat_gemini,
    "codex":       _chat_codex,
}

def ai_chat(prompt: str, system: str = "", max_tokens: int = 4096, quality: bool = False) -> str:
    backend = _BACKENDS.get(AI_PROVIDER)
    if not backend:
        raise ValueError(f"Unknown AI_PROVIDER '{AI_PROVIDER}'. Choose: claude, claude_code, gemini, codex")
    return backend(prompt, system, max_tokens, quality)

# Alias so all existing stage scripts continue to work without changes
claude_chat = ai_chat


def ai_chat_blocks(blocks: list, system: str = "", max_tokens: int = 4096, quality: bool = False) -> str:
    """Claude-only: send structured content blocks supporting per-block cache_control.
    Falls back to plain ai_chat for non-Claude providers (cache_control is ignored).
    Only the metered "claude" API provider uses the structured/cached path; "claude_code"
    (subscription CLI) joins blocks like gemini/codex since per-block caching is unsupported."""
    if AI_PROVIDER != "claude":
        text = "\n\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return ai_chat(text, system=system, max_tokens=max_tokens, quality=quality)
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {
        "model":      _resolve_model(quality),
        "max_tokens": max_tokens,
        "messages":   [{"role": "user", "content": blocks}],
    }
    if system:
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    resp = client.messages.create(**kwargs)
    return resp.content[0].text


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


def parse_json_response(text: str) -> dict:
    """Parse JSON from an LLM response, tolerating ```json fences and prose.

    Raises ValueError if no JSON object can be recovered.
    """
    s = text.strip()
    # Strip ``` / ```json fences if present
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end + 1])
        raise ValueError(f"Could not parse JSON from response:\n{text[:500]}")

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
            "Location":     {"rich_text": [{"text": {"content": job.get("location", "")}}]},
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


# ── Notion → Supabase sync (used before --evaluate run) ──────

def sync_notion_to_supabase() -> int:
    """Sync jobs marked 'Reviewed' in Notion to Supabase.

    User marks jobs as 'Reviewed' in Notion to indicate they want to apply.
    This syncs only jobs that have 'Reviewed' in Notion but NOT in Supabase.
    Returns the number of rows updated.
    """
    if not NOTION_API_KEY:
        return 0
    updated = 0
    try:
        import requests
        db = _get_db()

        # Query Notion API directly for jobs with "Reviewed" status
        headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28"}
        body = {
            "filter": {"property": "Status", "select": {"equals": "Reviewed"}},
        }
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            json=body,
            headers=headers,
        )
        results = resp.json() if resp.ok else {}

        for page in results.get("results", []):
            notion_page_id = page["id"]
            res = db.table("jobs").select("id,status").eq("notion_page_id", notion_page_id).execute()
            # Only update if Supabase status is NOT yet "Reviewed"
            if res.data and res.data[0]["status"] != "Reviewed":
                db.table("jobs").update({"status": "Reviewed"}).eq("id", res.data[0]["id"]).execute()
                updated += 1
    except Exception as e:
        log(f"[sync_notion_to_supabase] warning: {e}")
    return updated


# ── Notion intake (manually-added "Interested" jobs) ─────────

def _notion_plain_text(prop: dict) -> str:
    """Extract plain text from a Notion title or rich_text property dict."""
    if not prop:
        return ""
    parts = prop.get("title") or prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts).strip()


def get_notion_jobs_by_status(status: str) -> list[dict]:
    """Return Notion pages with the given Status (e.g. 'Interested') that the
    user added by hand. Each dict: {notion_page_id, url, title, company, location}.
    Skips rows without a Job URL. Returns [] if Notion isn't configured."""
    if not NOTION_API_KEY:
        return []
    jobs = []
    try:
        import requests
        headers = {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": "2022-06-28"}
        body = {"filter": {"property": "Status", "select": {"equals": status}}}
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            json=body,
            headers=headers,
        )
        results = resp.json().get("results", []) if resp.ok else []
        for page in results:
            props = page.get("properties", {})
            url = (props.get("Job URL") or {}).get("url")
            if not url:
                continue
            jobs.append({
                "notion_page_id": page["id"],
                "url":            url,
                "title":          _notion_plain_text(props.get("Job Title")),
                "company":        _notion_plain_text(props.get("Company")),
                "location":       _notion_plain_text(props.get("Location")),
            })
    except Exception as e:
        log(f"[get_notion_jobs_by_status] warning: {e}")
    return jobs


def _notion_promote_to_scraped(notion_page_id: str, job: dict):
    """Update an EXISTING manually-added Notion page to Status='Scraped',
    set ATS score + Date Scraped, and backfill Title/Company/Location if blank."""
    if not NOTION_API_KEY or not notion_page_id:
        return
    try:
        from notion_client import Client as NotionClient
        notion = NotionClient(auth=NOTION_API_KEY)
        props = {
            "Status":       {"select": {"name": "Scraped"}},
            "Date Scraped": {"date": {"start": today()}},
        }
        if job.get("ats_score"):
            props["ATS Match Score"] = {"number": float(job["ats_score"])}
        # Backfill text fields only when the user left them blank
        if job.get("title"):
            props["Job Title"] = {"title": [{"text": {"content": job["title"]}}]}
        if job.get("company"):
            props["Company"] = {"rich_text": [{"text": {"content": job["company"]}}]}
        if job.get("location"):
            props["Location"] = {"rich_text": [{"text": {"content": job["location"]}}]}
        notion.pages.update(page_id=notion_page_id, properties=props)
    except Exception:
        pass


# ── Public DB interface ───────────────────────────────────────

def db_find_job_by_url(url: str) -> str | None:
    """Return Supabase job id if URL already exists, else None."""
    res = _get_db().table("jobs").select("id").eq("job_url", url).execute()
    return res.data[0]["id"] if res.data else None


def db_add_job(job: dict) -> str:
    """Insert job into Supabase, mirror to Notion if key set. Returns Supabase id.

    Prerequisite: run once in Supabase SQL editor if upgrading from an older schema:
      ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_description text;
    """
    db = _get_db()
    row = {
        "job_title":        job.get("title", ""),
        "company":          job.get("company", ""),
        "location":         job.get("location", ""),
        "job_url":          job["url"],
        "status":           "Scraped",
        "date_scraped":     today(),
        "ats_match_score":  float(job.get("ats_score") or 0),
        "job_description":  job.get("description", "") or "",
    }
    res = db.table("jobs").insert(row).execute()
    supabase_id = res.data[0]["id"]

    notion_page_id = _notion_write_job(job)
    if notion_page_id:
        db.table("jobs").update({"notion_page_id": notion_page_id}).eq("id", supabase_id).execute()

    return supabase_id


def db_add_job_linked(job: dict, notion_page_id: str) -> str:
    """Insert a Supabase row for a job whose Notion page ALREADY exists (a
    manually-added 'Interested' row). Unlike db_add_job, this does not create a
    new Notion page — it links to the existing one and promotes it to 'Scraped'.
    Returns the Supabase id."""
    db = _get_db()
    row = {
        "job_title":        job.get("title", ""),
        "company":          job.get("company", ""),
        "location":         job.get("location", ""),
        "job_url":          job["url"],
        "status":           "Scraped",
        "date_scraped":     today(),
        "ats_match_score":  float(job.get("ats_score") or 0),
        "job_description":  job.get("description", "") or "",
        "notion_page_id":   notion_page_id,
    }
    res = db.table("jobs").insert(row).execute()
    supabase_id = res.data[0]["id"]
    _notion_promote_to_scraped(notion_page_id, job)
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
        .select("id,job_title,company,location,job_url,ats_match_score,tailored_resume_link")
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
            "location":    r.get("location") or "",
            "url":         r["job_url"],
            "ats":         r["ats_match_score"] or 0,
            "resume_link": r["tailored_resume_link"] or "",
        }
        for r in res.data
    ]


def db_get_job_description(job_id: str) -> str:
    """Return the cached job_description for a Supabase job id, or '' if absent."""
    res = _get_db().table("jobs").select("job_description").eq("id", job_id).execute()
    return (res.data[0].get("job_description") or "") if res.data else ""


def db_get_jobs(status: str, min_score: float = 0) -> list:
    """Jobs filtered by status and min ATS score, sorted by score desc."""
    res = (
        _get_db().table("jobs")
        .select("id,job_title,company,location,job_url,ats_match_score,tailored_resume_link")
        .eq("status", status)
        .gte("ats_match_score", min_score)
        .order("ats_match_score", desc=True)
        .execute()
    )
    return [
        {
            "page_id":     r["id"],
            "id":          r["id"],
            "title":       r["job_title"],
            "company":     r["company"],
            "location":    r.get("location") or "",
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
        .select("id,job_title,company,job_url,location,hiring_manager,hiring_manager_linkedin")
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
