#!/usr/bin/env python3
"""
autoapply.py — Stage 7: Auto-Apply subsystem (Phase 1 planning + Phase 2 fill handoff)
──────────────────────────────────────────────────────────────────────────────────────────
Spec: docs/backlog/step-10-auto-apply-subsystem.md

Picks up where stage 2 stops: a job sits at `Resume Tailored` with a tailored .docx, and a
human would otherwise re-type every answer by hand. This stage decides every answer, gates on
anything it can't answer confidently, and emits an answer sheet — optionally driving a browser
to pre-fill the real form (scripts/autoapply_browser.py).

WHY THERE IS NO SUBMIT HERE
    There is no candidate-usable application-submit API for any mainstream ATS. Greenhouse's
    POST /v1/boards/{token}/jobs/{id} authenticates as the *employer* (Basic Auth with the
    company's board key); their own docs warn a direct post "would reveal your secret key to
    anybody that views source". Lever/Ashby are the same. Only the READ side is public. So
    applying is a browser problem, and the final Submit click stays with the human — see the
    "structurally cannot write Applied" note below.

TWO LAYERS, DELIBERATELY DECOUPLED
    Layer 1 (this module)  — route, read the schema where public, resolve every field, gate,
                             write Notion, emit an answer sheet. No browser. Survives any ATS
                             markup change, and is the half that actually saves the time.
    Layer 2 (autoapply_browser) — Playwright pre-fill of the live form. Fragile by nature
                             (selector drift is what archived every comparable open-source
                             project); isolated here so it can break without taking Layer 1 down.

GOVERNING RULE — the profile supplies facts, AI only drafts prose. Work authorization,
sponsorship, salary and any yes/no eligibility answer come from APPLICATION_PROFILE or the
field is flagged review_required. Never guessed. A wrong answer there is disqualifying and
unretractable, so this is enforced in code (_resolve_field), not by prompt wording.

Run:
  python run.py --stage 7                 # plan + answer sheets for every Resume Tailored job
  python run.py --stage 7 --fill          # also pre-fill the form in a browser (stops before submit)
  python scripts/autoapply.py --sample    # offline: plan against the bundled schema
  python scripts/autoapply.py --url <greenhouse job>   # live schema fetch
"""

from __future__ import annotations

import sys
import json
import html
import argparse
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import (
    APPLICATION_PROFILE, EEO_RESPONSES, COMMON_QUESTION_PRESETS, APPLICATION_ADDRESS,
    AUTOAPPLY_DAILY_CAP, AUTOAPPLY_HEADLESS, APPLICATIONS_DIR, RESUMES_DIR,
)
from scripts.utils import (
    log, today, ensure_dirs,
    db_get_jobs, db_update_status_verified, db_get_job_description,
)

ROOT = Path(__file__).parent.parent


# ── Notion statuses this stage may write ──────────────────────────────────────
# NOTE: none of these is "Applied", and that is load-bearing. Comparable open-source
# auto-appliers are widely reported to mark jobs applied that were never actually submitted
# (captcha stalls, silent form errors), which corrupts the tracker in the worst possible
# direction — you never re-apply to a job you believe you already applied to. This stage never
# submits, so it must never claim success. `Applied` is set by the human, by hand, after they
# click Submit. test_autoapply_notion.py asserts no code path here can write it.
STATUS_QUEUED       = "Application Queued"
STATUS_NEEDS_Q      = "Needs Human: Question"
STATUS_NEEDS_CAPTCHA = "Needs Human: Captcha"
STATUS_NEEDS_AUTH   = "Needs Human: Auth"
STATUS_FAILED       = "Apply Failed"

WRITABLE_STATUSES = {
    STATUS_QUEUED, STATUS_NEEDS_Q, STATUS_NEEDS_CAPTCHA, STATUS_NEEDS_AUTH, STATUS_FAILED,
}


# ── 1. Channel router ─────────────────────────────────────────────────────────
_CHANNEL_DOMAINS = {
    "greenhouse": ("greenhouse.io",),
    "lever":      ("lever.co",),
    "ashby":      ("ashbyhq.com",),
    "workday":    ("myworkdayjobs.com", "workday.com"),
    "linkedin":   ("linkedin.com",),
    "indeed":     ("indeed.com",),
}

CHANNEL_POLICY = {
    "greenhouse": "semi-auto (schema-driven fill); public question schema available",
    "lever":      "semi-auto (fill); no public question schema — form may ask more than we plan for",
    "ashby":      "semi-auto (fill); expect captcha handoff",
    "workday":    "assisted only; per-company tenant account + email verify required",
    "linkedin":   "MANUAL ONLY — automated applying violates ToS and is behaviorally flagged",
    "indeed":     "MANUAL ONLY — automated applying prohibited",
    "unknown":    "answer sheet only; apply by hand",
}

# Channels the browser layer is allowed to touch at all. LinkedIn/Indeed are absent by rule,
# not by configuration: automated applying there violates their ToS, is behaviorally detected
# (reported thresholds put even ~15-30 applies/day in the danger zone), and driving an
# authenticated session has been observed doing visible damage — one comparable project's bot
# clicked recruiter *message* buttons mid-conversation. Answer sheet only, forever.
FILLABLE_CHANNELS = {"greenhouse", "lever"}


def detect_apply_channel(url: str) -> str:
    """Map a job URL to an apply channel. Returns 'unknown' for the custom long tail.

    Matches on a real domain boundary — host == d or host endswith '.' + d — so a lookalike
    like `evilgreenhouse.io` or `notlever.co` does NOT route to a trusted channel (a bare
    `endswith(d)` would match both).
    """
    if not url:
        return "unknown"
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    for channel, domains in _CHANNEL_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return channel
    return "unknown"


def parse_greenhouse_url(url: str) -> tuple[str | None, str | None]:
    """Extract (board_token, job_id) from any Greenhouse job URL shape in the wild:
        boards.greenhouse.io/{token}/jobs/{id}
        job-boards.greenhouse.io/{token}/jobs/{id}
        boards.greenhouse.io/embed/job_app?token={id}&for={token}
        <any greenhouse url>?gh_jid={id}          (the id carried as a query param)
    Returns (None, None) when neither the path nor the query yields both halves.
    """
    p = urlparse(url)
    parts = [seg for seg in (p.path or "").split("/") if seg]
    qs = parse_qs(p.query or "")
    token = job_id = None

    if "jobs" in parts:
        i = parts.index("jobs")
        if i >= 1:
            token = parts[i - 1]
        if i + 1 < len(parts):
            job_id = parts[i + 1]

    # embed/job_app?token={job_id}&for={board_token} — note Greenhouse's confusing naming:
    # here `token` is the JOB id and `for` is the board token.
    if "job_app" in parts:
        job_id = job_id or (qs.get("token") or [None])[0]
        token = token or (qs.get("for") or [None])[0]

    # ?gh_jid= is appended by aggregators linking into a board.
    job_id = job_id or (qs.get("gh_jid") or [None])[0]
    if token is None and parts:
        # A board token as the first path segment, when the id came from the query string.
        candidate = parts[0]
        if candidate not in ("embed", "jobs"):
            token = candidate

    return token, job_id


# ── 2. Read the public application-field schema ───────────────────────────────
def fetch_greenhouse_questions(board_token: str, job_id: str, timeout: int = 12) -> dict:
    """Fetch the live Greenhouse application question schema (the only public apply-side data
    any mainstream ATS exposes). Returns parsed JSON with a top-level 'questions' array."""
    import urllib.request
    url = (f"https://boards-api.greenhouse.io/v1/boards/{board_token}"
           f"/jobs/{job_id}?questions=true")
    req = urllib.request.Request(url, headers={"User-Agent": "careerpilot-autoapply/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# The fields every ATS application asks for, used where no public schema exists (Lever/Ashby/
# custom). Deliberately marked schema_known=False by the caller so the readiness verdict never
# claims completeness it can't have — the real form will likely ask more.
GENERIC_QUESTIONS = {
    "questions": [
        {"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input_text"}]},
        {"label": "Last Name",  "required": True, "fields": [{"name": "last_name",  "type": "input_text"}]},
        {"label": "Email",      "required": True, "fields": [{"name": "email",      "type": "input_text"}]},
        {"label": "Phone",      "required": False, "fields": [{"name": "phone",     "type": "input_text"}]},
        {"label": "Resume/CV",  "required": True, "fields": [{"name": "resume",     "type": "input_file"}]},
        {"label": "LinkedIn Profile", "required": False, "fields": [{"name": "linkedin", "type": "input_text"}]},
    ],
}

# A bundled, real-shaped Greenhouse ?questions=true payload for offline runs and tests.
SAMPLE_QUESTIONS = {
    "title": "Senior Software Engineer, Backend",
    "questions": [
        {"label": "First Name", "required": True,
         "fields": [{"name": "first_name", "type": "input_text"}]},
        {"label": "Last Name", "required": True,
         "fields": [{"name": "last_name", "type": "input_text"}]},
        {"label": "Email", "required": True,
         "fields": [{"name": "email", "type": "input_text"}]},
        {"label": "Phone", "required": True,
         "fields": [{"name": "phone", "type": "input_text"}]},
        {"label": "Resume/CV", "required": True,
         "fields": [{"name": "resume", "type": "input_file"}]},
        {"label": "LinkedIn Profile", "required": False,
         "fields": [{"name": "question_li", "type": "input_text"}]},
        {"label": "Are you legally authorized to work in the United States?", "required": True,
         "fields": [{"name": "question_workauth", "type": "multi_value_single_select",
                     "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]},
        {"label": "Will you now or in the future require sponsorship for employment visa status?",
         "required": True,
         "fields": [{"name": "question_sponsor", "type": "multi_value_single_select",
                     "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]},
        {"label": "Why do you want to work here?", "required": False,
         "fields": [{"name": "question_why", "type": "textarea"}]},
        {"label": "How did you hear about this job?", "required": False,
         "fields": [{"name": "question_source", "type": "input_text"}]},
        {"label": "Gender", "required": False,
         "fields": [{"name": "gender", "type": "multi_value_single_select",
                     "values": [{"label": "Male", "value": 1}, {"label": "Female", "value": 2},
                                {"label": "Decline To Self Identify", "value": 3}]}]},
    ],
}


# ── 3. Resolve every field ────────────────────────────────────────────────────
# status ∈ {"ready", "review_required"}

_FIELD_MAP = {
    "first_name": "first_name",
    "last_name":  "last_name",
    "email":      "email",
    "phone":      "phone",
}

# Label-keyword → profile key. Ordered: the eligibility knockouts that MUST be deterministic
# come first so a vaguely-worded label can't fall through to a looser rule.
_LABEL_RULES = [
    (("authorized to work", "legally authorized", "work authorization"), "work_authorized"),
    (("require sponsorship", "need sponsorship", "visa sponsorship", "sponsorship for employment"),
     "requires_sponsorship"),
    (("linkedin",),                                    "linkedin_url"),
    (("github",),                                      "github_url"),
    (("portfolio", "personal website"),                "portfolio_url"),
    (("gender", "race", "ethnicity", "veteran", "disability", "self identify"), "__eeo__"),
    # Structured address — matched on label text, not field name: Greenhouse's `name`
    # attributes here are opaque/internal, unlike the confirmed-stable first/last/email/phone
    # names in _FIELD_MAP, but these labels are confirmed from a live fetch (SmithRx job).
    (("legal first name",),                            "legal_first_name"),
    (("legal last name",),                              "legal_last_name"),
    (("address line 1",),                               "address_line1"),
    (("address line 2",),                               "address_line2"),
    (("city",),                                         "city"),
    (("state", "province"),                             "state"),
    (("country",),                                      "country"),
    (("zip code", "zip/postal", "postal code"),         "zip_code"),
    (("address type",),                                 "address_type"),
]

_ELIGIBILITY_KEYS = ("work_authorized", "requires_sponsorship")


def _eeo_answer(label: str) -> str:
    """Pick the matching EEO preset for a demographic question label."""
    l = (label or "").lower()
    for key, answer in EEO_RESPONSES.items():
        if key in l:
            return answer
    return EEO_RESPONSES.get("gender", "Decline To Self Identify")


def _preset_answer(label: str) -> str | None:
    """Look the label up in the common-screener answer bank. Returns None on no match, and ''
    when a preset exists but is intentionally blank (→ review_required, not a guess)."""
    l = (label or "").lower()
    for pattern, answer in COMMON_QUESTION_PRESETS.items():
        if pattern in l:
            return answer
    return None


def _resolve_field(label: str, field: dict, profile: dict, resume_path: str) -> dict:
    """Resolve one form field to a plan entry. Never guesses an eligibility answer."""
    fname = (field.get("name") or "").lower()
    ftype = field.get("type", "input_text")
    label_l = (label or "").lower()

    # (a) File uploads → the stage 2 tailored resume.
    if ftype in ("input_file", "attachment") or fname in ("resume", "cv"):
        return {"type": ftype, "value": resume_path,
                "status": "ready" if resume_path else "review_required",
                "source": "stage2_resume" if resume_path else "resume-missing"}

    # (b) Direct name map (first/last/email/phone).
    if fname in _FIELD_MAP:
        pkey = _FIELD_MAP[fname]
        val = profile.get(pkey, "")
        return {"type": ftype, "value": val,
                "status": "ready" if val else "review_required",
                "source": f"profile.{pkey}" if val else f"profile.{pkey} (empty)"}

    # (c) Label rules — eligibility knockouts, EEO, links.
    for keys, pkey in _LABEL_RULES:
        if any(k in label_l for k in keys):
            if pkey == "__eeo__":
                answer = _eeo_answer(label)
                # A blank EEO preset means "no preference recorded", not "answer with empty".
                # Filling an empty value into a real demographic field would silently submit a
                # non-answer where a deliberate decline was intended.
                return {"type": ftype, "value": answer,
                        "status": "ready" if answer else "review_required",
                        "source": "EEO_RESPONSES" if answer else "EEO_RESPONSES (blank)"}
            val = profile.get(pkey)
            if pkey in _ELIGIBILITY_KEYS:
                # Unset eligibility is ALWAYS human-reviewed. Never defaulted, never inferred:
                # a wrong answer here is disqualifying and cannot be retracted.
                if val is None:
                    return {"type": ftype, "value": None, "status": "review_required",
                            "source": "eligibility unset (never guessed)"}
                return {"type": ftype, "value": bool(val), "status": "ready",
                        "source": f"profile.{pkey}"}
            return {"type": ftype, "value": val,
                    "status": "ready" if val else "review_required",
                    "source": f"profile.{pkey}" if val else f"profile.{pkey} (empty)"}

    # (d) Common-screener answer bank.
    preset = _preset_answer(label)
    if preset is not None:
        return {"type": ftype, "value": preset,
                "status": "ready" if preset else "review_required",
                "source": "COMMON_QUESTION_PRESETS" if preset else
                          "COMMON_QUESTION_PRESETS (blank — set an answer to automate this)"}

    # (e) Free-text → a human writes it. The model may draft prose, but never unreviewed.
    if ftype == "textarea":
        return {"type": ftype, "value": None, "status": "review_required",
                "source": "free-text (human writes/reviews)"}

    # (f) Anything else → human.
    return {"type": ftype, "value": None, "status": "review_required", "source": "unmapped"}


def build_application_plan(schema: dict, profile: dict = None, resume_path: str = "",
                           schema_known: bool = True) -> dict:
    """Turn a question schema into a per-field application plan."""
    profile = profile if profile is not None else {**APPLICATION_PROFILE, **APPLICATION_ADDRESS}
    entries = []
    for q in schema.get("questions", []):
        label = q.get("label", "")
        required = bool(q.get("required"))
        fields = q.get("fields", [])
        # Greenhouse emits two field rows for one logical attachment question (an input_file
        # plus a textarea for pasting the text instead) under the same label. Resolving the
        # textarea independently would count it as an unresolved free-text question even
        # though the upload already answers it — mirror the attachment's resolution instead.
        has_attachment = any(f.get("type") in ("input_file", "attachment") for f in fields)
        attachment_entry = None
        for field in fields:
            ftype = field.get("type", "input_text")
            if ftype == "textarea" and has_attachment:
                if attachment_entry is None:
                    attach_field = next(f for f in fields
                                        if f.get("type") in ("input_file", "attachment"))
                    attachment_entry = _resolve_field(label, attach_field, profile, resume_path)
                entry = dict(attachment_entry)
                entry["source"] = attachment_entry["source"] + " (dedup: attachment textarea)"
            else:
                entry = _resolve_field(label, field, profile, resume_path)
                if ftype in ("input_file", "attachment"):
                    attachment_entry = entry
            entry.update({"label": label, "required": required, "name": field.get("name")})
            entries.append(entry)
    return {"title": schema.get("title", ""), "fields": entries, "schema_known": schema_known}


def readiness_report(plan: dict) -> dict:
    """Can this be pre-filled, or does it need a human first?

    A blocking (required + unresolved) field is the only thing that stops the fill — that gate
    is the ONLY guard, since Greenhouse explicitly does not validate required fields
    server-side. When the schema isn't public (Lever/Ashby/custom) the verdict is hedged: we
    genuinely do not know what else the form will ask.
    """
    fields = plan["fields"]
    review = [f for f in fields if f["status"] == "review_required"]
    blocking = [f for f in review if f["required"]]
    ready = [f for f in fields if f["status"] == "ready"]

    if blocking:
        verdict, status = "NEEDS HUMAN — required fields unresolved", STATUS_NEEDS_Q
    elif not plan.get("schema_known", True):
        verdict, status = "PARTIAL — no public schema; form may ask more", STATUS_QUEUED
    elif review:
        verdict, status = "READY — optional fields left blank", STATUS_QUEUED
    else:
        verdict, status = "READY — every field resolved", STATUS_QUEUED

    return {
        "verdict": verdict, "notion_status": status,
        "ready": ready, "review": review, "blocking": blocking,
        "counts": {"total": len(fields), "ready": len(ready),
                   "review": len(review), "blocking": len(blocking)},
    }


# ── 4. Resume resolution ──────────────────────────────────────────────────────
def resolve_tailored_resume(job: dict) -> str:
    """Resolve the stage 2 tailored .docx back to a real local path.

    Stage 2 can have written Tailored Resume Link in one of two schemes, mirroring its own
    local/CI split (scripts/stage2_tailor.py::_tailored_resume_link()):
      - file://{absolute path} (local runs): reverse it directly (strip scheme, percent-decode,
        fix the leading slash Windows drive paths pick up) and confirm the file still exists —
        it may have been moved or cleaned up since tailoring.
      - https://raw.githubusercontent.com/.../tailored-resumes/... (CI-tailored jobs): there's
        no local file yet, so download it into RESUMES_DIR and return that path instead.
    Returns "" when there's no usable resume, which makes the upload field review_required
    rather than silently attaching nothing — a download failure hits this same path.
    """
    link = (job.get("resume_link") or "").strip()
    if not link:
        return ""
    if link.startswith("http://") or link.startswith("https://"):
        return _download_tailored_resume(link)
    path = unquote(link[7:]) if link.startswith("file://") else unquote(link)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":   # /C:/... → C:/...
        path = path[1:]
    p = Path(path)
    if not p.exists():
        log(f"  ⚠ Tailored resume missing on disk: {p}")
        return ""
    return str(p)


def _download_tailored_resume(url: str) -> str:
    """Fetch a CI-tailored resume from its raw.githubusercontent.com URL into RESUMES_DIR,
    reusing the branch's filename so re-runs overwrite rather than accumulate duplicates.
    Mirrors resolve_tailored_resume()'s "" + log-warning contract on any failure."""
    import requests
    ensure_dirs()
    filename = url.rsplit("/", 1)[-1]
    dest = Path(RESUMES_DIR) / filename
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            log(f"  ⚠ Tailored resume download failed ({r.status_code}): {url}")
            return ""
        dest.write_bytes(r.content)
    except requests.RequestException as e:
        log(f"  ⚠ Tailored resume download failed: {url} ({e})")
        return ""
    return str(dest)


# ── 5. Answer sheet ───────────────────────────────────────────────────────────
def _answer_sheet_html(job: dict, plan: dict, rpt: dict, channel: str) -> str:
    """A self-contained page listing every question and the answer to give, so applying by
    hand takes under a minute instead of re-deriving everything per form."""
    def row(f):
        mark = "✔" if f["status"] == "ready" else ("⛔" if f["required"] else "○")
        val = f["value"]
        if f["type"] in ("input_file", "attachment"):
            shown = html.escape(str(val)) if val else "<em>no resume found</em>"
        elif val is None:
            shown = "<em>you write this</em>"
        elif isinstance(val, bool):
            shown = "Yes" if val else "No"
        else:
            shown = html.escape(str(val)) or "<em>blank</em>"
        cls = "ready" if f["status"] == "ready" else ("blocking" if f["required"] else "optional")
        return (f'<tr class="{cls}"><td>{mark}</td><td>{html.escape(f["label"])}</td>'
                f'<td>{shown}</td><td class="src">{html.escape(f["source"])}</td></tr>')

    c = rpt["counts"]
    rows = "\n".join(row(f) for f in plan["fields"])
    hedge = ("" if plan.get("schema_known", True) else
             '<p class="warn">No public field schema for this board — the real form will '
             'likely ask questions beyond the ones listed here.</p>')
    return f"""<!doctype html><meta charset="utf-8">
<title>Apply — {html.escape(job.get('company',''))} — {html.escape(job.get('title',''))}</title>
<style>
 body{{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem}}
 h1{{font-size:1.4rem;margin-bottom:.2rem}} .meta{{color:#666;margin-bottom:1.2rem}}
 table{{border-collapse:collapse;width:100%}} td,th{{padding:.5rem .6rem;border-bottom:1px solid #eee;vertical-align:top}}
 tr.blocking{{background:#fff4f4}} tr.ready td:first-child{{color:#0a0}} .src{{color:#888;font-size:.85em}}
 .warn{{background:#fffbe6;border-left:3px solid #e6c000;padding:.6rem .8rem}}
 .verdict{{font-weight:600;margin:.6rem 0 1rem}}
</style>
<h1>{html.escape(job.get('company',''))} — {html.escape(job.get('title',''))}</h1>
<div class="meta">
  <a href="{html.escape(job.get('url',''))}">{html.escape(job.get('url',''))}</a><br>
  channel: {html.escape(channel)} · {html.escape(CHANNEL_POLICY.get(channel,''))}
</div>
<div class="verdict">{html.escape(rpt['verdict'])} —
  {c['total']} fields, {c['ready']} ready, {c['review']} need you ({c['blocking']} required)</div>
{hedge}
<table><tr><th></th><th>Question</th><th>Answer</th><th>from</th></tr>
{rows}
</table>
<p class="warn">This stage never submits. Review the answers, submit yourself, then set
Status = <strong>Applied</strong> in Notion.</p>
"""


def write_answer_sheet(job: dict, plan: dict, rpt: dict, channel: str) -> str:
    ensure_dirs()
    out_dir = ROOT / APPLICATIONS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_company = "".join(ch for ch in job.get("company", "") if ch.isalnum() or ch in " _-").strip()
    safe_role = "".join(ch for ch in job.get("title", "") if ch.isalnum() or ch in " _-").strip()
    stem = f"{today()}_{safe_company}_{safe_role}".replace(" ", "_") or f"{today()}_application"
    path = out_dir / f"{stem}.html"
    path.write_text(_answer_sheet_html(job, plan, rpt, channel), encoding="utf-8")
    return str(path)


# ── 6. Per-job planning ───────────────────────────────────────────────────────
def plan_for_job(job: dict) -> tuple[str, dict, dict]:
    """Build (channel, plan, report) for one job. Never raises on a fetch failure — a schema
    we couldn't read degrades to the generic field set rather than skipping the job."""
    channel = detect_apply_channel(job.get("url", ""))
    resume_path = resolve_tailored_resume(job)
    schema, schema_known = GENERIC_QUESTIONS, False

    if channel == "greenhouse":
        token, job_id = parse_greenhouse_url(job.get("url", ""))
        if token and job_id:
            try:
                schema, schema_known = fetch_greenhouse_questions(token, job_id), True
            except Exception as e:
                log(f"  ⚠ Greenhouse schema fetch failed ({e}) — falling back to generic fields.")
        else:
            log(f"  ⚠ Could not parse board token/job id from {job.get('url','')}")

    plan = build_application_plan(schema, resume_path=resume_path, schema_known=schema_known)
    if not plan.get("title"):
        plan["title"] = job.get("title", "")
    return channel, plan, readiness_report(plan)


# ── 7. Stage runner ───────────────────────────────────────────────────────────
def run(min_score: int = 0, fill: bool = False, limit: int = 0, dry_run: bool = False):
    """Plan applications for every `Resume Tailored` job.

    Idempotency: a job is transitioned off `Resume Tailored` (to Application Queued or a
    Needs Human state) before anything else happens, and the transition is *verified* — if
    Notion silently dropped the status (the select option doesn't exist), the job is skipped
    rather than left to be re-processed on the next run.

    `dry_run` does everything except write to Notion: it still reads jobs, builds real plans and
    writes real answer sheets, so you can evaluate the output on real jobs before letting the
    stage touch the tracker. Nothing is transitioned, so a dry run is repeatable — the same jobs
    are still sitting at `Resume Tailored` afterwards.
    """
    cap = limit or AUTOAPPLY_DAILY_CAP
    jobs = db_get_jobs("Resume Tailored", min_score)
    if not jobs:
        log("No jobs at 'Resume Tailored'. Run stage 2 first.")
        return

    log(f"Stage 7 — {len(jobs)} tailored job(s); cap {cap}/run"
        f"{' · browser fill ON' if fill else ''}"
        f"{' · DRY RUN (no Notion writes)' if dry_run else ''}")
    if len(jobs) > cap:
        log(f"  ↳ capping to {cap}. High application velocity is itself a negative signal: "
            f"ATSes score it and flag high-volume submitters before a human reads the app.")
        jobs = jobs[:cap]

    queued = needs_human = skipped = 0
    for job in jobs:
        log(f"\n▶ {job.get('company','')} — {job.get('title','')}")
        channel, plan, rpt = plan_for_job(job)
        log(f"  channel: {channel} · {CHANNEL_POLICY.get(channel, '')}")
        c = rpt["counts"]
        log(f"  {rpt['verdict']} ({c['ready']}/{c['total']} ready, {c['blocking']} blocking)")

        sheet = write_answer_sheet(job, plan, rpt, channel)
        log(f"  ✓ Answer sheet: {sheet}")

        status = rpt["notion_status"]
        reason = ", ".join(f["label"] for f in rpt["blocking"])
        extra = {
            "apply_channel": channel,
            "apply_attempts": (job.get("apply_attempts") or 0) + 1,
            "application_log": f"{today()} planned via {channel}; sheet={Path(sheet).name}",
        }
        if reason:
            extra["needs_human_reason"] = reason

        if dry_run:
            log(f"  ○ dry run — would set Status = {status}"
                + (f" ({reason})" if reason else ""))
            queued += 1
            continue

        if not db_update_status_verified(job["page_id"], status, extra):
            skipped += 1
            continue

        if status == STATUS_NEEDS_Q:
            needs_human += 1
            log(f"  ⛔ Needs you first: {reason}")
            continue
        queued += 1

        if fill and channel in FILLABLE_CHANNELS:
            _fill_one(job, plan, channel)
        elif fill:
            log(f"  ○ No browser fill for '{channel}' — apply from the answer sheet by hand.")

    if dry_run:
        log(f"\nDry run done. {queued} job(s) planned, answer sheets written to "
            f"{APPLICATIONS_DIR}/. Notion was NOT touched — every job is still at "
            f"'Resume Tailored', so re-run freely.")
        return

    log(f"\nDone. {queued} queued, {needs_human} need you, {skipped} skipped (Notion status "
        f"not applied). Nothing was submitted — review each sheet, submit yourself, then set "
        f"Status = Applied.")


def _fill_one(job: dict, plan: dict, channel: str):
    """Hand off to the browser layer. Isolated + guarded: a fill failure must never take down
    the planning half, which is the part that actually saved the time."""
    try:
        from scripts.autoapply_browser import fill_application
    except Exception as e:
        log(f"  ⚠ Browser layer unavailable ({e}) — answer sheet still written.")
        return
    result = fill_application(job.get("url", ""), plan, headless=AUTOAPPLY_HEADLESS)
    if result.get("ok"):
        log(f"  ✓ Form pre-filled ({result.get('filled', 0)} fields). "
            f"Screenshot: {result.get('screenshot', '-')}")
        log("  → Review it in the browser and click Submit yourself.")
        return

    outcome = result.get("outcome", "failed")
    status = {"captcha": STATUS_NEEDS_CAPTCHA, "auth": STATUS_NEEDS_AUTH}.get(outcome, STATUS_FAILED)
    log(f"  ✗ Fill stopped ({outcome}): {result.get('detail', '')}")
    db_update_status_verified(job["page_id"], status, {
        "needs_human_reason": result.get("detail", outcome),
        "apply_channel": channel,
    })


# ── 8. CLI (standalone plan inspection) ───────────────────────────────────────
def _print_report(plan: dict, rpt: dict):
    c = rpt["counts"]
    log(f"\n📋 Application plan — {plan['title'] or '(untitled)'}")
    log(f"   verdict: {rpt['verdict']}")
    log(f"   fields: {c['total']} total | {c['ready']} ready | "
        f"{c['review']} need human ({c['blocking']} of them required)\n")
    for f in plan["fields"]:
        mark = "✔" if f["status"] == "ready" else ("⛔" if f["required"] else "○")
        req = "required" if f["required"] else "optional"
        val = f["value"]
        shown = "<file>" if f["type"] in ("input_file", "attachment") else (
            "…you write this…" if val is None else repr(val))
        log(f"   {mark} [{req:8}] {f['label'][:52]:52}  → {shown}   ({f['source']})")
    log("")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stage 7 auto-apply — plan only, never submits.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--sample", action="store_true", help="Bundled Greenhouse schema (offline).")
    src.add_argument("--url", help="Live job URL (Greenhouse fetches its real schema).")
    ap.add_argument("--json", action="store_true", help="Machine-readable output.")
    ap.add_argument("--resume", default="", help="Tailored resume path to plan against.")
    args = ap.parse_args(argv)

    # --json must emit nothing but JSON on stdout so it can be piped.
    say = (lambda _msg: None) if args.json else log

    if args.url:
        channel = detect_apply_channel(args.url)
        say(f"🔎 channel = {channel}  ({CHANNEL_POLICY.get(channel, '')})")
        _, plan, rpt = plan_for_job({"url": args.url, "resume_link": args.resume})
    else:
        say("🔎 channel = greenhouse  (bundled sample schema; no network used)")
        plan = build_application_plan(SAMPLE_QUESTIONS, resume_path=args.resume)
        rpt = readiness_report(plan)

    if args.json:
        print(json.dumps({"plan": plan,
                          "report": {k: v for k, v in rpt.items()
                                     if k not in ("ready", "review", "blocking")}},
                         indent=2, default=str))
    else:
        _print_report(plan, rpt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
