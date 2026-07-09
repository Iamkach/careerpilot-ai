#!/usr/bin/env python3
"""
workflow.py — Claude Agent SDK orchestrator for the job search pipeline
──────────────────────────────────────────────────────────────────────
Claude decides *which* stage runs and with what arguments; the stages themselves are the
same `scripts/stage*.py` functions that `run.py` calls. There is exactly one implementation
of every behavior — filters, Indeed scraping, .docx tailoring, Notion intake, and drop logs
are inherited from the stage scripts rather than re-derived here.

Usage:
  python workflow.py                                          # Morning pipeline (scrape + review digest)
  python workflow.py --task scrape                           # Stage 1: scrape LinkedIn + Indeed
  python workflow.py --task ingest                           # Ingest Notion "Interested" jobs
  python workflow.py --task evaluate --min-score 65          # Stages 2-4: tailor + outreach + digest
  python workflow.py --task tailor --min-score 65            # Stage 2: tailor "Reviewed" jobs
  python workflow.py --task outreach --company "Stripe"      # Stage 3: cold outreach
  python workflow.py --task digest --send                    # Stage 4: email digest
  python workflow.py --task interview --company "Meta" --role "Senior PM"
  python workflow.py --task negotiate --company "Stripe" --role "PM" --offer 185000
"""

import sys, os, io, json, asyncio, argparse, contextlib, threading, traceback
from pathlib import Path
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from config.settings import (
    NOTION_DB_ID,
    TARGET_ROLES,
    RESUME_PATH,
    YOUR_NAME, YOUR_EMAIL, YOUR_BIO,
    AI_MODEL_OVERRIDE, QUALITY_MODEL,
)

# Force subscription auth: the Agent SDK spawns the `claude` CLI, which uses the logged-in
# subscription only when ANTHROPIC_API_KEY is absent from the environment. The stage scripts
# never read this env var — they get their key from config/settings.py directly (see
# scripts/utils.py) — so popping it here is safe regardless of AI_PROVIDER.
os.environ.pop("ANTHROPIC_API_KEY", None)

from claude_agent_sdk import (
    query, ClaudeAgentOptions, tool, create_sdk_mcp_server,
    AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
)


# ── Stage invocation ──────────────────────────────────────────────────
# Each tool is a thin wrapper over a `scripts/stageN_*.run()` function. The stage prints its
# own progress; we tee that to the terminal (so the user watches it live) and hand the text
# back to Claude as the tool result, so it can summarize what actually happened.

class _Tee(io.TextIOBase):
    """Write to the real stdout and an in-memory buffer at once."""

    def __init__(self, real, buffer):
        self._real, self._buffer = real, buffer

    def write(self, s):
        self._real.write(s)
        self._buffer.write(s)
        return len(s)

    def flush(self):
        self._real.flush()

    def writable(self):
        return True

    def fileno(self):
        return self._real.fileno()

    @property
    def encoding(self):
        return getattr(self._real, "encoding", "utf-8")


# Stage functions print to sys.stdout, which _Tee rebinds process-globally. Only one stage
# may run at a time or two concurrent tool calls (Claude can emit several in one turn) would
# nest _Tee context managers across threads and leave sys.stdout wrapped permanently.
_STAGE_LOCK = threading.Lock()


def _truncate(text: str, head: int = 1000, tail: int = 2000) -> str:
    """Keep the head (early per-job lines) and tail (the stage's summary) so long runs
    don't lose the detail Claude is asked to report on."""
    if len(text) <= head + tail:
        return text
    return text[:head] + "\n…\n" + text[-tail:]


def _call_stage(fn, **kwargs) -> dict:
    """Run a blocking stage function, capturing its log output for Claude."""
    buffer = io.StringIO()
    with _STAGE_LOCK:
        try:
            with contextlib.redirect_stdout(_Tee(sys.stdout, buffer)):
                result = fn(**kwargs)
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "output": _truncate(buffer.getvalue()),
            }
    out = {"success": True, "output": _truncate(buffer.getvalue())}
    if result is not None:
        out["result"] = result
    return out


def _impl_run_scrape() -> dict:
    from scripts.stage1_scrape import run
    return _call_stage(run)


def _impl_run_ingest_interested() -> dict:
    from scripts.utils import load_resume
    from scripts.stage1_scrape import ingest_interested_from_notion
    result = _call_stage(ingest_interested_from_notion, resume=load_resume())
    if result["success"]:
        result["ingested"] = result.pop("result", 0)
    return result


def _impl_run_tailor(min_score: float = 0) -> dict:
    from scripts.stage2_tailor import run
    return _call_stage(run, min_score=int(min_score))


def _impl_run_outreach(company: str = "", contact: str = "", contact_role: str = "") -> dict:
    from scripts.stage3_outreach import run
    return _call_stage(
        run,
        target_company=company or None,
        contact=contact or None,
        contact_role=contact_role,
        no_confirm=True,  # agentic path never prompts; drafts are saved for review
    )


def _impl_run_digest(mode: str = "ready", send: bool = False) -> dict:
    from scripts.stage4_digest import run
    return _call_stage(run, send=send, mode=mode)


def _impl_run_interview_prep(
    company: str, role: str = "", jd_file: str = "", hm_linkedin: str = ""
) -> dict:
    from scripts.stage5_interview_prep import run
    return _call_stage(run, company=company, role=role, jd_file=jd_file, hm_linkedin=hm_linkedin)


def _impl_run_negotiate(company: str, role: str, offer: float = 0) -> dict:
    from scripts.stage6_negotiate import run
    return _call_stage(run, company=company, role=role, offer=offer)


# ── Read-only visibility into Notion ──────────────────────────────────
# Claude uses these to report on pipeline state; they never mutate anything.

def _impl_get_jobs(status: str, min_score: float = 0) -> dict:
    from scripts.utils import db_get_jobs
    jobs = db_get_jobs(status=status, min_score=min_score)
    return {"jobs": jobs, "count": len(jobs)}


def _impl_get_ready_to_apply() -> dict:
    from scripts.utils import db_get_ready_to_apply
    jobs = db_get_ready_to_apply()
    for job in jobs:
        job.setdefault("ats_score", job.get("ats", 0))
    return {"jobs": jobs, "count": len(jobs)}


# ── Tool dispatch ─────────────────────────────────────────────────────

_TOOL_IMPL = {
    "run_scrape":            _impl_run_scrape,
    "run_ingest_interested": _impl_run_ingest_interested,
    "run_tailor":            _impl_run_tailor,
    "run_outreach":          _impl_run_outreach,
    "run_digest":            _impl_run_digest,
    "run_interview_prep":    _impl_run_interview_prep,
    "run_negotiate":         _impl_run_negotiate,
    "get_jobs":              _impl_get_jobs,
    "get_ready_to_apply":    _impl_get_ready_to_apply,
}

_STATUSES = [
    "Interested", "Scraped", "Reviewed", "Resume Tailored", "Applied",
    "Outreach Sent", "Interview Scheduled", "Offer Received", "Disregard",
]

TOOLS = [
    {
        "name": "run_scrape",
        "description": (
            "Run Stage 1: ingest Notion 'Interested' jobs, scrape LinkedIn + Indeed via Apify for "
            "every target role, apply the company/title/location/sponsorship/applicant pre-filters, "
            "score survivors against the resume, and save new jobs to Notion as 'Scraped'. "
            "Handles dedup, filtering, and scoring internally — do not attempt those yourself."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_ingest_interested",
        "description": (
            "Ingest only the jobs hand-picked in Notion (Status='Interested'): enrich via Apify, "
            "score, and promote each existing page to 'Scraped' in place. Skips the LinkedIn scrape. "
            "Hand-picked jobs bypass the pre-filters by design."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_tailor",
        "description": (
            "Run Stage 2: fetch 'Reviewed' jobs from Notion, apply targeted ATS keyword edits to the "
            "base resume .docx (preserving formatting), save to output/resumes/, and set each job's "
            "status to 'Resume Tailored'. Does NOT mark jobs as applied."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_score": {"type": "number", "default": 0, "description": "Minimum ATS score to tailor"},
            },
            "required": [],
        },
    },
    {
        "name": "run_outreach",
        "description": (
            "Run Stage 3: draft cold or warm outreach emails for ready-to-apply jobs and save them to "
            "output/outreach/. Pass `contact` to write a warm referral message instead of a cold email. "
            "Drafts are saved, never sent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company":      {"type": "string", "default": "", "description": "Limit to one company"},
                "contact":      {"type": "string", "default": "", "description": "Contact name for a warm referral"},
                "contact_role": {"type": "string", "default": "", "description": "Contact's role"},
            },
            "required": [],
        },
    },
    {
        "name": "run_digest",
        "description": (
            "Run Stage 4: build an HTML digest and save it to output/. "
            "mode='scraped' renders the review digest of newly scraped jobs (used after scraping); "
            "mode='ready' renders the ready-to-apply digest of tailored jobs. "
            "Set send=true to email it via Gmail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["ready", "scraped"], "default": "ready"},
                "send": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "run_interview_prep",
        "description": "Run Stage 5: generate an HTML interview prep guide into output/prep_guides/.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company":     {"type": "string"},
                "role":        {"type": "string", "default": ""},
                "jd_file":     {"type": "string", "default": ""},
                "hm_linkedin": {"type": "string", "default": ""},
            },
            "required": ["company"],
        },
    },
    {
        "name": "run_negotiate",
        "description": "Run Stage 6: research salary benchmarks and write an HTML negotiation brief.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "role":    {"type": "string"},
                "offer":   {"type": "number", "default": 0, "description": "Current base offer, if known"},
            },
            "required": ["company", "role"],
        },
    },
    {
        "name": "get_jobs",
        "description": (
            "Read jobs from Notion filtered by status and minimum ATS score, sorted by score descending. "
            "Read-only — use it to report on pipeline state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status":    {"type": "string", "enum": _STATUSES},
                "min_score": {"type": "number", "default": 0},
            },
            "required": ["status"],
        },
    },
    {
        "name": "get_ready_to_apply",
        "description": (
            "Read all jobs with Status='Resume Tailored' and no Date Applied. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _print_tool_outcome(result: dict):
    if not result.get("success", True):
        print(f"     ✗ {result.get('error', 'failed')}")
    elif "count" in result:
        print(f"     → {result['count']} item(s)")


def _make_tool(name: str, description: str, schema: dict, impl):
    """Wrap a sync `_impl_*` function (+ its JSON schema) as an SDK in-process tool. The
    blocking impl runs in a thread so it doesn't stall the event loop."""
    @tool(name, description, schema)
    async def _t(args):
        try:
            result = await asyncio.to_thread(impl, **args)
        except Exception as e:
            result = {"success": False, "error": str(e)}
        _print_tool_outcome(result)
        return {"content": [{"type": "text", "text": json.dumps(result)}]}
    return _t


_SDK_TOOLS = [
    _make_tool(t["name"], t["description"], t["input_schema"], _TOOL_IMPL[t["name"]])
    for t in TOOLS
]
_SERVER  = create_sdk_mcp_server(name="jobpipe", version="2.0.0", tools=_SDK_TOOLS)
_ALLOWED = [f"mcp__jobpipe__{t['name']}" for t in TOOLS]


# ── Task prompts ──────────────────────────────────────────────────────
# Prompts describe intent and reporting, not procedure — the stages own the procedure.

def _task_morning(args) -> str:
    return f"""Today is {date.today().isoformat()}. Run the morning scrape and review digest.

  1. Call run_scrape. It scrapes LinkedIn + Indeed for every target role, filters, scores,
     and saves new jobs to Notion. It also ingests any 'Interested' jobs.
  2. Call run_digest(mode="scraped") to render the review digest.
  3. Call get_jobs(status="Scraped") and summarize the top matches by ATS score.

This is SCRAPE ONLY — do not tailor any resumes. Report how many jobs were added, how many
were dropped by each filter (the scrape output lists this), and remind the user to mark jobs
as Reviewed in Notion before running --task evaluate."""


def _task_scrape(args) -> str:
    return f"""Today is {date.today().isoformat()}. Call run_scrape, then summarize its output:
how many jobs were added, how many were dropped by each filter, and the top-scoring jobs.
Call get_jobs(status="Scraped") if you need the details."""


def _task_ingest(args) -> str:
    return """Call run_ingest_interested to pull the jobs hand-picked in Notion, then report how
many were promoted to 'Scraped'. Remind the user to mark them Reviewed before tailoring."""


def _task_tailor(args) -> str:
    min_score = getattr(args, "min_score", 0)
    return f"""Call run_tailor(min_score={min_score}). It reads 'Reviewed' jobs from Notion and
patches the base resume .docx per job.

If it reports no 'Reviewed' jobs, tell the user to mark jobs as Reviewed in Notion first —
do not fall back to tailoring 'Scraped' jobs; the review gate is deliberate.

Summarize which companies got a tailored resume and where the files landed."""


def _task_evaluate(args) -> str:
    min_score = getattr(args, "min_score", 0)
    company      = getattr(args, "company", None) or ""
    contact      = getattr(args, "contact", None) or ""
    contact_role = getattr(args, "contact_role", "") or ""
    outreach_args = (
        f"company={json.dumps(company)}, contact={json.dumps(contact)}, "
        f"contact_role={json.dumps(contact_role)}"
    )
    return f"""Today is {date.today().isoformat()}. The user has marked good jobs as Reviewed in
Notion. Run the evaluate pipeline:

  1. run_tailor(min_score={min_score})
  2. run_outreach({outreach_args})
  3. run_digest(mode="ready")

Then call get_ready_to_apply and summarize: how many resumes were tailored, how many outreach
drafts were written, and how many jobs are in the ready digest. Stop early and explain if a
step reports nothing to do."""


def _task_outreach(args) -> str:
    company      = getattr(args, "company", None) or ""
    contact      = getattr(args, "contact", None) or ""
    contact_role = getattr(args, "contact_role", "") or ""
    return f"""Call run_outreach(company={json.dumps(company)}, contact={json.dumps(contact)}, \
contact_role={json.dumps(contact_role)}).
It drafts {"a warm referral message" if contact else "cold emails"} for ready-to-apply jobs and
saves them to output/outreach/. Report which drafts were saved and remind the user they are not sent."""


def _task_digest(args) -> str:
    send = bool(getattr(args, "send", False))
    return f"""Call run_digest(mode="ready", send={str(send).lower()}), then call get_ready_to_apply
and print a plain-text summary of the jobs in the digest, sorted by ATS score.
{"The digest will be emailed to " + YOUR_EMAIL + "." if send else "The digest is saved to output/ but not emailed."}"""


def _task_interview(args) -> str:
    company     = getattr(args, "company", "") or ""
    role        = getattr(args, "role", "") or ""
    jd_file     = getattr(args, "jd_file", "") or ""
    hm_linkedin = getattr(args, "hm_linkedin", "") or ""
    return f"""Call run_interview_prep(company={json.dumps(company)}, role={json.dumps(role)}, \
jd_file={json.dumps(jd_file)}, hm_linkedin={json.dumps(hm_linkedin)}), then tell the user where
the guide was saved and summarize the sections it covers."""


def _task_negotiate(args) -> str:
    company = getattr(args, "company", "") or ""
    role    = getattr(args, "role", "") or ""
    offer   = getattr(args, "offer", 0)
    return f"""Call run_negotiate(company={json.dumps(company)}, role={json.dumps(role)}, \
offer={offer}), then tell the user where the brief was saved and summarize the recommended
opening position."""


_TASK_BUILDERS = {
    "morning":   _task_morning,
    "scrape":    _task_scrape,
    "ingest":    _task_ingest,
    "tailor":    _task_tailor,
    "evaluate":  _task_evaluate,
    "outreach":  _task_outreach,
    "digest":    _task_digest,
    "interview": _task_interview,
    "negotiate": _task_negotiate,
}


# ── System prompt ─────────────────────────────────────────────────────

def _build_system(resume: str) -> str:
    return f"""You are an AI job search assistant for {YOUR_NAME} ({YOUR_EMAIL}).

You orchestrate a 6-stage job search pipeline. Each stage is already implemented as a tool that
runs tested Python. Your job is to decide WHICH stage runs, with WHAT arguments, and to report
clearly on what happened — not to re-implement a stage's work yourself.

Pipeline:
  Stage 1 (run_scrape)          — scrape + filter + score → Notion, Status='Scraped'
  Stage 2 (run_tailor)          — 'Reviewed' jobs → tailored .docx → Status='Resume Tailored'
  Stage 3 (run_outreach)        — draft cold/warm emails → output/outreach/
  Stage 4 (run_digest)          — HTML digest (mode='scraped' review, or mode='ready')
  Stage 5 (run_interview_prep)  — HTML interview prep guide
  Stage 6 (run_negotiate)       — HTML salary negotiation brief

Status flow: Interested → Scraped → Reviewed → Resume Tailored → Applied → …
The Scraped → Reviewed step is a MANUAL gate. The user marks jobs Reviewed in Notion by hand.
Never try to move a job to 'Reviewed' yourself, and never tailor 'Scraped' jobs.

Rules:
  — Never score jobs, filter companies, or write resume text yourself. The stage tools do that,
    with filters and formatting you cannot reproduce. Call the tool.
  — A stage tool returns its own log output. Read it and summarize faithfully. If a stage says
    it found nothing to do, say so plainly rather than working around it.
  — get_jobs and get_ready_to_apply are read-only; use them for reporting.
  — If a stage tool returns success=false, report the error to the user and STOP. Do not retry
    the same call — stages like run_scrape hit paid external APIs (Apify) on every call.

Candidate profile:
  Name:         {YOUR_NAME}
  Email:        {YOUR_EMAIL}
  Bio:          {YOUR_BIO}
  Target roles: {', '.join(TARGET_ROLES)}
  Notion DB:    https://www.notion.so/{NOTION_DB_ID.replace('-', '')}

Base resume, for context when summarizing matches:

<resume>
{resume}
</resume>"""


# ── Agentic loop ──────────────────────────────────────────────────────

_MAX_TURNS = 30  # stages do the heavy lifting now; the loop only sequences them


async def _run(task_prompt: str, system_str: str):
    opts = ClaudeAgentOptions(
        system_prompt=system_str,
        model=QUALITY_MODEL or AI_MODEL_OVERRIDE or "sonnet",
        mcp_servers={"jobpipe": _SERVER},
        allowed_tools=_ALLOWED,        # pre-approve only our jobpipe tools
        permission_mode="dontAsk",     # deny anything not pre-approved
        strict_mcp_config=True,        # ignore any user/project MCP servers
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

    system_str  = _build_system(resume)
    task_prompt = _TASK_BUILDERS[task](args)

    banner = f"Claude Workflow — {task.upper()}"
    print(f"\n{'─' * len(banner)}")
    print(banner)
    print(f"{'─' * len(banner)}\n")

    asyncio.run(_run(task_prompt, system_str))


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Job Search — Claude Agent SDK orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--task", default="morning",
        choices=list(_TASK_BUILDERS),
        help="Which task to run (default: morning = scrape + review digest)",
    )
    parser.add_argument("--min-score",    type=int,   default=0,  dest="min_score",
                        help="Minimum ATS score for the tailor stage")
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
                        help="Current offer amount for the negotiation brief")
    parser.add_argument("--send",         action="store_true",
                        help="Send digest via Gmail (requires OAuth credentials)")
    args = parser.parse_args()

    if args.task == "interview" and not args.company:
        parser.error("--task interview requires --company")
    if args.task == "negotiate" and (not args.company or not args.role):
        parser.error("--task negotiate requires --company and --role")

    run_workflow(args.task, args)


if __name__ == "__main__":
    main()
