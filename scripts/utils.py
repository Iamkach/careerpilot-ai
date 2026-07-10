"""
utils.py — Shared helpers used across all job search scripts
"""
import os, json, sys, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config.settings import *
import config.settings as _settings
# Alternate-provider keys are optional under the default claude_code provider. Ensure the
# names are always defined so `import *` users don't NameError when they're absent.
ANTHROPIC_API_KEY = getattr(_settings, "ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = getattr(_settings, "GEMINI_API_KEY", "")
OPENAI_API_KEY    = getattr(_settings, "OPENAI_API_KEY", "")

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


async def _sdk_text(prompt: str, system: str, model: str) -> str:
    """One-shot prompt->text via the Agent SDK, no tools. Accumulates assistant text,
    preferring the final ResultMessage.result when present."""
    from claude_agent_sdk import (
        query, ClaudeAgentOptions, AssistantMessage, TextBlock, ResultMessage,
    )
    opts = ClaudeAgentOptions(
        system_prompt=system or None,
        model=model,
        allowed_tools=[],          # pure text generation — no tool use
        setting_sources=[],        # don't load project CLAUDE.md/settings into the prompt
        permission_mode="bypassPermissions",
        max_turns=1,
    )
    chunks, result = [], None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(msg, ResultMessage):
            result = msg.result
    return (result if result else "".join(chunks)).strip()


def _chat_claude_code(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    """Route a single prompt->text call through the Claude Code subscription via the Agent
    SDK (no metered API key). The SDK spawns the `claude` CLI as its transport, so it uses
    the logged-in subscription as long as ANTHROPIC_API_KEY is not in the environment.
    Note: prompt caching is unavailable over this path; `max_tokens` has no SDK knob."""
    import asyncio
    os.environ.pop("ANTHROPIC_API_KEY", None)  # force subscription auth, never metered
    _find_claude_cli()  # fail fast with a clear message if the CLI is missing
    return asyncio.run(_sdk_text(prompt, system, _resolve_model(quality)))


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

def _active_provider() -> str:
    """Return STAGE_AI_PROVIDER if set, else AI_PROVIDER."""
    from config.settings import STAGE_AI_PROVIDER
    return STAGE_AI_PROVIDER or AI_PROVIDER

def ai_chat(prompt: str, system: str = "", max_tokens: int = 4096, quality: bool = False) -> str:
    provider = _active_provider()
    backend = _BACKENDS.get(provider)
    if not backend:
        raise ValueError(f"Unknown provider '{provider}'. Choose: claude, claude_code, gemini, codex")
    return backend(prompt, system, max_tokens, quality)

# Alias so all existing stage scripts continue to work without changes
claude_chat = ai_chat


def ai_chat_blocks(blocks: list, system: str = "", max_tokens: int = 4096, quality: bool = False) -> str:
    """Claude-only: send structured content blocks supporting per-block cache_control.
    Falls back to plain ai_chat for non-Claude providers (cache_control is ignored).
    Only the metered "claude" API provider uses the structured/cached path; "claude_code"
    (subscription CLI) joins blocks like gemini/codex since per-block caching is unsupported."""
    if _active_provider() != "claude":
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
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                pass
        # Also try outermost [...] span for batch array responses
        start, end = s.find("["), s.rfind("]")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end + 1])
        raise ValueError(f"Could not parse JSON from response:\n{text[:500]}")

def ensure_dirs():
    for d in [OUTPUT_DIR, RESUMES_DIR, PREP_GUIDES_DIR]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)

def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── Notion (primary data store) ──────────────────────────────

_NOTION = None

def _notion():
    """Cached notion_client. Raises if NOTION_API_KEY is unset (Notion is the only store)."""
    global _NOTION
    if not NOTION_API_KEY:
        raise RuntimeError("NOTION_API_KEY is not set — Notion is the primary data store.")
    if _NOTION is None:
        from notion_client import Client as NotionClient
        _NOTION = NotionClient(auth=NOTION_API_KEY)
    return _NOTION


# ── Notion property readers ───────────────────────────────────

def _prop_url(props: dict, name: str) -> str:
    return (props.get(name) or {}).get("url") or ""

def _prop_number(props: dict, name: str):
    return (props.get(name) or {}).get("number") or 0

def _prop_date(props: dict, name: str):
    d = (props.get(name) or {}).get("date")
    return d.get("start") if d else None


def _page_to_job(page: dict) -> dict:
    """Map a Notion page to the job dict shape every stage/tool expects."""
    props = page.get("properties", {})
    ats = _prop_number(props, "ATS Match Score")
    return {
        "page_id":     page["id"],
        "id":          page["id"],
        "title":       _notion_plain_text(props.get("Job Title")),
        "company":     _notion_plain_text(props.get("Company")),
        "location":    _notion_plain_text(props.get("Location")),
        "url":         _prop_url(props, "Job URL"),
        "ats":         ats,
        "ats_score":   ats,
        "resume_link": _prop_url(props, "Tailored Resume Link"),
        "hm":          _notion_plain_text(props.get("Hiring Manager")),
        "hm_li":       _prop_url(props, "Hiring Manager LinkedIn"),
    }


# ── Job description ↔ page body blocks ────────────────────────
# The JD is cached in the page body (paragraph blocks) so stages 2/5 don't re-fetch it.

def _jd_blocks(description: str) -> list:
    """Chunk a (possibly long) JD into Notion paragraph blocks (≤1900 chars each)."""
    chunks = [description[i:i + 1900] for i in range(0, len(description), 1900)] or [""]
    return [
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}}]}}
        for c in chunks
    ]


# ── Notion writers (page create / status update) ──────────────

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


# ── Notion is now the single source of truth ─────────────────

def sync_notion_to_supabase() -> int:
    """No-op since Notion is the primary store: 'Reviewed' status is read straight from
    Notion (db_get_jobs(status='Reviewed')). Kept so existing callers don't break."""
    return 0


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


# ── Public DB interface (Notion-backed) ───────────────────────
# `job_id` / `page_id` everywhere is the Notion page id.

def _query_db(filter_=None, sorts=None) -> list:
    """Query the Notion jobs database, following pagination. Returns raw pages."""
    pages, cursor = [], None
    while True:
        kwargs = {"database_id": NOTION_DB_ID}
        if filter_:
            kwargs["filter"] = filter_
        if sorts:
            kwargs["sorts"] = sorts
        if cursor:
            kwargs["start_cursor"] = cursor
        res = _notion().databases.query(**kwargs)
        pages.extend(res.get("results", []))
        if res.get("has_more"):
            cursor = res.get("next_cursor")
        else:
            break
    return pages


def db_find_job_by_url(url: str) -> str | None:
    """Return the Notion page id if a job with this URL exists, else None."""
    if not url:
        return None
    try:
        pages = _query_db(filter_={"property": "Job URL", "url": {"equals": url}})
        return pages[0]["id"] if pages else None
    except Exception as e:
        log(f"[db_find_job_by_url] warning: {e}")
        return None


def db_add_job(job: dict) -> str:
    """Create a Notion page (Status='Scraped') for a scraped job, caching the JD in the
    page body. Returns the Notion page id."""
    page_id = _notion_write_job(job)
    if not page_id:
        raise RuntimeError("Notion page creation failed — check NOTION_API_KEY and DB sharing.")
    desc = job.get("description", "") or ""
    if desc:
        try:
            _notion().blocks.children.append(block_id=page_id, children=_jd_blocks(desc))
        except Exception as e:
            log(f"[db_add_job] JD body append warning: {e}")
    return page_id


def db_add_job_linked(job: dict, notion_page_id: str) -> str:
    """Promote a manually-added 'Interested' Notion page to 'Scraped' (set ATS/date,
    backfill fields) and cache the JD in its body. Returns the same page id."""
    _notion_promote_to_scraped(notion_page_id, job)
    desc = job.get("description", "") or ""
    if desc:
        try:
            _notion().blocks.children.append(block_id=notion_page_id, children=_jd_blocks(desc))
        except Exception as e:
            log(f"[db_add_job_linked] JD body append warning: {e}")
    return notion_page_id


def db_update_status(job_id: str, status: str, extra_props: dict = None):
    """Update a job's Status (+ mapped extra props) on its Notion page."""
    _notion_update(job_id, status, extra_props)


def db_get_ready_to_apply() -> list:
    """Jobs with Status='Resume Tailored' and no Date Applied, sorted by score desc."""
    pages = _query_db(
        filter_={"and": [
            {"property": "Status", "select": {"equals": "Resume Tailored"}},
            {"property": "Date Applied", "date": {"is_empty": True}},
        ]},
        sorts=[{"property": "ATS Match Score", "direction": "descending"}],
    )
    return [_page_to_job(p) for p in pages]


def db_get_job_description(job_id: str) -> str:
    """Return the JD cached in the page body (paragraph blocks), or '' if none."""
    try:
        texts, cursor = [], None
        while True:
            kwargs = {"block_id": job_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            res = _notion().blocks.children.list(**kwargs)
            for b in res.get("results", []):
                if b.get("type") == "paragraph":
                    texts.append("".join(t.get("plain_text", "") for t in b["paragraph"]["rich_text"]))
            if res.get("has_more"):
                cursor = res.get("next_cursor")
            else:
                break
        return "\n".join(t for t in texts if t).strip()
    except Exception as e:
        log(f"[db_get_job_description] warning: {e}")
        return ""


def db_get_jobs(status: str, min_score: float = 0) -> list:
    """Jobs filtered by status and min ATS score, sorted by score desc."""
    conditions = [{"property": "Status", "select": {"equals": status}}]
    if min_score:
        conditions.append({"property": "ATS Match Score",
                           "number": {"greater_than_or_equal_to": min_score}})
    pages = _query_db(
        filter_={"and": conditions} if len(conditions) > 1 else conditions[0],
        sorts=[{"property": "ATS Match Score", "direction": "descending"}],
    )
    return [_page_to_job(p) for p in pages]


def db_get_all_jobs() -> list[dict]:
    """Fetch ALL rows from the Notion jobs DB in a few paginated reads (no filter).
    Each dict: page_id, title, company, location, url, status, ats_score.
    Returns [] on failure — dedup then falls back to per-run seen_urls only."""
    try:
        pages = _query_db()  # no filter → all rows, follows pagination
    except Exception as e:
        log(f"[db_get_all_jobs] warning: {e}")
        return []
    jobs = []
    for p in pages:
        props = p.get("properties", {})
        jobs.append({
            "page_id":   p["id"],
            "title":     _notion_plain_text(props.get("Job Title")),
            "company":   _notion_plain_text(props.get("Company")),
            "location":  _notion_plain_text(props.get("Location")),
            "url":       _prop_url(props, "Job URL"),
            "status":    ((props.get("Status") or {}).get("select") or {}).get("name") or "",
            "ats_score": _prop_number(props, "ATS Match Score"),
        })
    return jobs


def db_get_job_by_company(company: str) -> dict | None:
    """Return the first job whose Company contains `company` (case-insensitive), or None."""
    try:
        pages = _query_db(filter_={"property": "Company", "rich_text": {"contains": company}})
        return _page_to_job(pages[0]) if pages else None
    except Exception as e:
        log(f"[db_get_job_by_company] warning: {e}")
        return None
