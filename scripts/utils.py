"""
utils.py — Shared helpers used across all job search scripts
"""
import os, json, re, sys, time, datetime
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

# ── Provider backends ────────────────────────────────────────

def _resolve_model(quality: bool, provider: str = "claude") -> str:
    """Resolve the model id for a call to `provider`. AI_MODEL_OVERRIDE/QUALITY_MODEL only
    apply to provider == "claude" (their values are Claude model ids, meaningless to other
    SDKs); other providers use MODEL_OVERRIDES[provider] if set, else that backend's built-in
    default. This is what lets AI_PROVIDER/FAST_PROVIDER/QUALITY_PROVIDER be switched to
    gemini/codex/claude_code at any time without also having to edit a model field."""
    tier = "quality" if quality else "fast"
    override = getattr(_settings, "MODEL_OVERRIDES", {}).get(provider, {}).get(tier, "")
    if override:
        return override
    if provider == "claude":
        legacy = (QUALITY_MODEL if quality else AI_MODEL_OVERRIDE) or ""
        if legacy:
            return legacy
    return _DEFAULTS.get(provider, _DEFAULTS["claude"])


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


_USAGE_CAP_PATTERNS = ("usage limit", "usage cap", "rate limit reached", "5-hour limit", "session limit")


def _chat_claude_code(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    """Route a single prompt->text call through the Claude Code subscription via the Agent
    SDK (no metered API key). The SDK spawns the `claude` CLI as its transport, so it uses
    the logged-in subscription (interactive login or CLAUDE_CODE_OAUTH_TOKEN for headless/CI
    auth) as long as ANTHROPIC_API_KEY is not in the environment.
    Note: prompt caching is unavailable over this path; `max_tokens` has no SDK knob."""
    import asyncio
    os.environ.pop("ANTHROPIC_API_KEY", None)  # force subscription auth, never metered
    _find_claude_cli()  # fail fast with a clear message if the CLI is missing
    try:
        return asyncio.run(_sdk_text(prompt, system, _resolve_model(quality, "claude_code")))
    except Exception as e:
        msg = str(e).lower()
        if any(p in msg for p in _USAGE_CAP_PATTERNS):
            raise RuntimeError(
                f"Claude Code subscription usage cap hit: {e}. Wait for the usage window to "
                "reset, or re-run with FAST_PROVIDER/QUALITY_PROVIDER=claude (metered) instead. "
                "Re-running is safe — stages are idempotent via Notion status."
            ) from e
        raise


def _chat_gemini(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    config = genai.types.GenerationConfig(max_output_tokens=max_tokens)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    model = genai.GenerativeModel(_resolve_model(quality, "gemini"))
    resp = model.generate_content(full_prompt, generation_config=config)
    return resp.text


def _chat_codex(prompt: str, system: str, max_tokens: int, quality: bool = False) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    model = _resolve_model(quality, "codex")
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


class AIChatError(RuntimeError):
    """Raised when an ai_chat()/ai_chat_blocks() call exhausts its retry budget.
    Callers (e.g. stage1_scrape.score_jobs_batch) must treat this as "unscored", never
    fabricate a placeholder result."""


class AIUsageCapError(AIChatError):
    """Raised immediately (no blind retry) when the Claude Code subscription's usage cap
    is hit — retrying a capped session just burns more of the same exhausted window."""


_RETRY_DELAYS = (2, 8)  # seconds; len(_RETRY_DELAYS) + 1 total attempts

_TRANSIENT_ERROR_PATTERNS = (
    "timeout", "timed out", "connection", "temporarily unavailable", "overloaded",
    "429", "500", "502", "503", "504", "rate limit",
)


def _is_usage_cap_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in _USAGE_CAP_PATTERNS)


def _is_transient_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in _TRANSIENT_ERROR_PATTERNS)


def _call_with_retry(call):
    """Run `call()`, retrying transient failures with exponential backoff. A usage-cap
    error is never retried (raised immediately as AIUsageCapError); a non-transient error
    (bad request, auth failure, etc.) is also not worth retrying and raises on first miss.
    Exhausting the retry budget on transient errors raises AIChatError."""
    last_err = None
    for attempt in range(1 + len(_RETRY_DELAYS)):
        try:
            return call()
        except Exception as e:
            if _is_usage_cap_error(e):
                raise AIUsageCapError(str(e)) from e
            last_err = e
            if not _is_transient_error(e) or attempt == len(_RETRY_DELAYS):
                break
            delay = _RETRY_DELAYS[attempt]
            log(f"[ai_chat] transient error ({e}); retrying in {delay}s "
                f"(attempt {attempt + 2}/{1 + len(_RETRY_DELAYS)})")
            time.sleep(delay)
    raise AIChatError(f"AI call failed after retries: {last_err}") from last_err


def _active_provider(quality: bool = False) -> str:
    """Pick the provider for this call. FAST_PROVIDER/QUALITY_PROVIDER (per-tier) take
    precedence when either differs from AI_PROVIDER (e.g. a nightly CI run splitting bulk
    calls onto metered and low-volume calls onto the subscription); otherwise falls through
    to STAGE_AI_PROVIDER or AI_PROVIDER, preserving today's single-provider behavior."""
    from config.settings import STAGE_AI_PROVIDER
    fast    = getattr(_settings, "FAST_PROVIDER", "") or AI_PROVIDER
    quality_provider = getattr(_settings, "QUALITY_PROVIDER", "") or AI_PROVIDER
    if fast != AI_PROVIDER or quality_provider != AI_PROVIDER:
        return quality_provider if quality else fast
    return STAGE_AI_PROVIDER or AI_PROVIDER

def ai_chat(prompt: str, system: str = "", max_tokens: int = 4096, quality: bool = False) -> str:
    provider = _active_provider(quality)
    backend = _BACKENDS.get(provider)
    if not backend:
        raise ValueError(f"Unknown provider '{provider}'. Choose: claude, claude_code, gemini, codex")
    return _call_with_retry(lambda: backend(prompt, system, max_tokens, quality))

# Alias so all existing stage scripts continue to work without changes
claude_chat = ai_chat


def ai_chat_blocks(blocks: list, system: str = "", max_tokens: int = 4096, quality: bool = False) -> str:
    """Claude-only: send structured content blocks supporting per-block cache_control.
    Falls back to plain ai_chat for non-Claude providers (cache_control is ignored).
    Only the metered "claude" API provider uses the structured/cached path; "claude_code"
    (subscription CLI) joins blocks like gemini/codex since per-block caching is unsupported."""
    if _active_provider(quality) != "claude":
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
    return _call_with_retry(lambda: client.messages.create(**kwargs).content[0].text)


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
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(line.encode(encoding, errors="replace").decode(encoding))


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

def _prop_select(props: dict, name: str):
    sel = (props.get(name) or {}).get("select")
    return sel.get("name") if sel else None


# ── Company-name matching (word-boundary, not substring) ─────
# Shared by stage1_scrape.py's SKIP_COMPANIES denylist and stage2_tailor.py's
# RESTRICTED_SPONSORSHIP_COMPANIES gate — both need "UST" to not match "Customer.io".

_LEGAL_SUFFIXES = {"inc", "incorporated", "llc", "corp", "corporation", "ltd", "co", "plc"}


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _strip_suffix(toks: list[str]) -> list[str]:
    """Trim trailing legal suffixes so "BeaconFire Inc." still matches bare "BeaconFire"."""
    while toks and toks[-1] in _LEGAL_SUFFIXES:
        toks = toks[:-1]
    return toks


def _subseq(haystack: list[str], needle: list[str]) -> bool:
    """True if `needle` appears as a contiguous, token-boundary-anchored sub-sequence of `haystack`."""
    if not needle:
        return False
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def matches_company_list(company: str, names: list[str]) -> bool:
    """True if `company` word-boundary-matches any entry in `names` (not a raw substring
    match — avoids false positives like "ust" matching "customer.io")."""
    haystack = _strip_suffix(_tokens(company))
    if not haystack:
        return False
    for name in names:
        needle = _strip_suffix(_tokens(name))
        if needle and _subseq(haystack, needle):
            return True
    return False


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
        "sponsorship":     _prop_select(props, "Sponsorship"),
        "scoring_attempts": _prop_number(props, "Scoring Attempts"),
        "notes":       _notion_plain_text(props.get("Notes")),
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
            "Status":       {"select": {"name": job.get("status") or "Scraped"}},
            "Date Scraped": {"date": {"start": today()}},
        }
        if job.get("ats_score") is not None:
            props["ATS Match Score"] = {"number": float(job["ats_score"])}
        if job.get("sponsorship") is not None:
            props["Sponsorship"] = {"select": {"name": job["sponsorship"]}}
        if job.get("scoring_attempts") is not None:
            props["Scoring Attempts"] = {"number": float(job["scoring_attempts"])}
        if job.get("posted_date"):
            props["Posted Date"] = {"date": {"start": job["posted_date"]}}
        if job.get("source"):
            props["Source"] = {"rich_text": [{"text": {"content": job["source"]}}]}
        if job.get("applicant_count") is not None:
            props["Applicant Count"] = {"number": float(job["applicant_count"])}
        if job.get("salary_range"):
            props["Salary Range"] = {"rich_text": [{"text": {"content": job["salary_range"]}}]}
        try:
            page = notion.pages.create(parent={"database_id": NOTION_DB_ID}, properties=props)
        except Exception as e:
            if "Sponsorship" in props and "Sponsorship" in str(e):
                log(f"[_notion_write_job] warning: Sponsorship write failed ({e}); retrying without it")
                del props["Sponsorship"]
                page = notion.pages.create(parent={"database_id": NOTION_DB_ID}, properties=props)
            else:
                raise
        return page["id"]
    except Exception as e:
        log(f"[_notion_write_job] Notion page creation failed: {e}")
        return None


# Maps snake_case extra_props keys → Notion property dicts
_EXTRA_TO_NOTION = {
    "tailored_resume_link":    lambda v: {"Tailored Resume Link": {"url": v}},
    "date_applied":            lambda v: {"Date Applied": {"date": {"start": v}}},
    "hiring_manager":          lambda v: {"Hiring Manager": {"rich_text": [{"text": {"content": v}}]}},
    "hiring_manager_linkedin": lambda v: {"Hiring Manager LinkedIn": {"url": v}},
    "notes":                   lambda v: {"Notes": {"rich_text": [{"text": {"content": v}}]}},
    "ats_score":               lambda v: {"ATS Match Score": {"number": float(v)}},
    "sponsorship":             lambda v: {"Sponsorship": {"select": {"name": v}}},
    "scoring_attempts":        lambda v: {"Scoring Attempts": {"number": float(v)}},
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


def _notion_promote_to_scraped(notion_page_id: str, job: dict, status: str = "Scraped"):
    """Update an EXISTING manually-added Notion page to the given Status (default 'Scraped'),
    set ATS score + Date Scraped, and backfill Title/Company/Location if blank."""
    if not NOTION_API_KEY or not notion_page_id:
        return
    try:
        from notion_client import Client as NotionClient
        notion = NotionClient(auth=NOTION_API_KEY)
        props = {
            "Status":       {"select": {"name": status}},
            "Date Scraped": {"date": {"start": today()}},
        }
        if job.get("ats_score") is not None:
            props["ATS Match Score"] = {"number": float(job["ats_score"])}
        if job.get("sponsorship") is not None:
            props["Sponsorship"] = {"select": {"name": job["sponsorship"]}}
        if job.get("scoring_attempts") is not None:
            props["Scoring Attempts"] = {"number": float(job["scoring_attempts"])}
        # Backfill text fields only when the user left them blank
        if job.get("title"):
            props["Job Title"] = {"title": [{"text": {"content": job["title"]}}]}
        if job.get("company"):
            props["Company"] = {"rich_text": [{"text": {"content": job["company"]}}]}
        if job.get("location"):
            props["Location"] = {"rich_text": [{"text": {"content": job["location"]}}]}
        try:
            notion.pages.update(page_id=notion_page_id, properties=props)
        except Exception as e:
            if "Sponsorship" in props and "Sponsorship" in str(e):
                log(f"[_notion_promote_to_scraped] warning: Sponsorship write failed ({e}); retrying without it")
                del props["Sponsorship"]
                notion.pages.update(page_id=notion_page_id, properties=props)
            else:
                raise
    except Exception as e:
        log(f"[_notion_promote_to_scraped] Notion update failed: {e}")


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


def db_find_job_by_url(url: str, exclude_page_id: str = "") -> str | None:
    """Return the Notion page id if a job with this URL exists, else None.

    `exclude_page_id` skips a hit whose id matches it — needed when checking a manually-added
    row against the rest of the DB, since that row already holds its own Job URL and would
    otherwise match itself."""
    if not url:
        return None
    try:
        pages = _query_db(filter_={"property": "Job URL", "url": {"equals": url}})
        for page in pages:
            if page["id"] != exclude_page_id:
                return page["id"]
        return None
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


def db_add_job_linked(job: dict, notion_page_id: str, status: str = "Scraped") -> str:
    """Promote a manually-added 'Interested' Notion page to `status` (default 'Scraped';
    pass 'Retry' when scoring failed) — sets ATS/date, backfills fields — and caches the JD
    in its body. Returns the same page id."""
    _notion_promote_to_scraped(notion_page_id, job, status=status)
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
    Raises RuntimeError on a failed read — callers must treat that as "unknown state" and
    abort rather than proceeding as if the DB were empty (a failure that fell through to []
    used to look identical to a genuinely empty DB, which would silently mass-duplicate the
    tracker on the next scrape)."""
    try:
        pages = _query_db()  # no filter → all rows, follows pagination
    except Exception as e:
        log(f"[db_get_all_jobs] read failed: {e}")
        raise RuntimeError(f"db_get_all_jobs() read failed: {e}") from e
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
