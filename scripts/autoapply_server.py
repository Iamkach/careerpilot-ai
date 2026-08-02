#!/usr/bin/env python3
"""
autoapply_server.py — Stage 7 Layer 3: local HTTP bridge for the browser extension
────────────────────────────────────────────────────────────────────────────────
Spec: docs/backlog/step-15b-plan-endpoint-identify-job.md (this increment)
      docs/backlog/step-15a-serve-bridge-scaffold.md (scaffold increment 0)
      docs/backlog/step-15-application-prefill-extension.md (epic — architecture/why)

WHAT THIS IS
    A loopback-only HTTP server (`python run.py --serve`) that a Chrome extension talks to
    so a human standing on a live application form can get it pre-filled.
      GET  /health        — no auth. Liveness probe.
      POST /plan          — DOM payload in, per-field application plan out.
      GET  /jobs/ready    — jobs at Status = 'Resume Tailored' (no Date Applied), score desc —
                             the side panel's job-list launcher (step-15h).
      GET  /resume/meta   — filename/size/mime/path of the matched job's tailored resume
                             (no bytes).
      GET  /resume        — the tailored resume's actual bytes, for the content script's
                             DataTransfer attach (step-15d). 403 on a read-only channel and on
                             any path that resolves outside RESUMES_DIR — the Notion row this
                             traces back to is user-editable and the browser is the caller, so
                             the resolved path is never trusted without that containment check.
    `/drafts` and `/confirm-applied` land in later `step-15*` stories.

ROUTING IS KEYED OFF THE LIVE PAGE URL — NEVER THE NOTION ROW'S URL. Those routinely differ
(a LinkedIn posting vs. the Greenhouse/Ashby/Workday page it redirects a human to), and that
difference is the entire reason this bridge exists. Consequently **this module does not reuse
`plan_for_job()`** (`scripts/autoapply.py:669`) — `build_plan_response()` below composes
`resolve_tailored_resume()` + `build_application_plan()` + `readiness_report()` itself against
the live-page schema. Restate this in every later story that touches this file; do not silently
drift from it.

IDENTIFYING WHOSE JOB THIS IS (`identify_job()`) — 3 rungs, plus a launcher rung 0:
    0. Known `page_id` (the extension's own job-list launcher, step-15h, already knows it) —
       short-circuits straight to that job, skipping the candidate pool and every other rung.
    1. Normalized URL match against the candidate pool (drop query/fragment, strip trailing
       `/apply`, fold `job-boards.`→`boards.`, lowercase host, strip trailing slash). Exact-URL
       match is this rung's degenerate case — same lookup, reported at higher confidence.
    2. Greenhouse `(board_token, job_id)` match via `parse_greenhouse_url()`, for aggregator
       links (`?gh_jid=`) normalization alone can't resolve.
    3. Ask — zero rung-1/2 hits: return the whole candidate pool so a human can pick (rendered
       by the panel in step-15c).
    Two or more matches at any rung is `ambiguous` and picks neither — fingerprint-style
    guessing was cut for v1 precisely because a wrong guess would attach the wrong resume.
    The candidate pool is every row at `WRITABLE_STATUSES | {"Resume Tailored"}`, not
    `Resume Tailored` alone — Stage 7's `run()` moves rows off that status, so a narrower pool
    would miss exactly the jobs Stage 7 already planned.

SECURITY (non-negotiable — see the epic's "Security" section)
    - Bind literal ("127.0.0.1", port) — never ("", port), which binds all interfaces.
    - A random token is generated on every `--serve` invocation and written to the git-ignored
      config/extension_token.txt. Every request (once authed routes exist) must carry it via the
      `Authorization: Bearer <token>` header; a missing/wrong token is rejected.
    - CORS: the response echoes back the request's own `Origin` header, never an extension-id
      allowlist — an unpacked extension's id changes every reload, so an id-keyed allowlist would
      silently break.
    - Only runs under an explicit `python run.py --serve`; never a background daemon.
    - `ThreadingHTTPServer` so one slow request (e.g. a future draft call) can't block a
      concurrent one (e.g. a future resume fetch).
    - LinkedIn/Indeed stay read-only: enforced HERE (server-side, keyed on the live page URL),
      not in the content script, so a bug or a hand-edited extension can't bypass it.
"""

from __future__ import annotations

import json
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.autoapply import (
    WRITABLE_STATUSES, detect_apply_channel, parse_greenhouse_url,
    build_application_plan, readiness_report, resolve_tailored_resume,
)
from scripts.autoapply_browser import accepts_docx
from scripts.render_docx import convert_docx_to_pdf
from scripts.utils import db_get_jobs, db_get_ready_to_apply
from config.settings import RESUMES_DIR

ROOT = Path(__file__).parent.parent
TOKEN_PATH = ROOT / "config" / "extension_token.txt"

DEFAULT_PORT = 8765

# Routes that exist but require no token (health checks only — never answer/plan data).
UNAUTHED_PATHS = {"/health"}

# Every status a live-navigated job could still be sitting at when the human opens the form —
# NOT "Resume Tailored" alone, since Stage 7's run() moves a row off it onto one of these the
# moment it's planned.
CANDIDATE_STATUSES = sorted(WRITABLE_STATUSES | {"Resume Tailored"})

# Enforced here, not in the content script: automated filling on these two channels violates
# ToS and is behaviorally detected (see autoapply.py's FILLABLE_CHANNELS comment). Deliberately
# a separate constant from FILLABLE_CHANNELS, which governs the unrelated Playwright layer.
_READONLY_CHANNELS = {"linkedin", "indeed"}
_READONLY_SOURCE = "channel read-only (linkedin/indeed) — never filled"

# Content-script DOM element kind → the internal field type build_application_plan() consumes
# (the same vocabulary Greenhouse's own ?questions=true schema uses). Anything unrecognized
# degrades to input_text rather than raising, so an unfamiliar input kind still resolves.
_DOM_TYPE_MAP = {
    "text": "input_text", "email": "input_text", "tel": "input_text", "url": "input_text",
    "number": "input_text", "textarea": "textarea", "select": "multi_value_single_select",
    "file": "input_file",
}


# ── Token file ─────────────────────────────────────────────────────────────────

def generate_token() -> str:
    """A fresh random token, regenerated on every --serve start (never reused across runs)."""
    return secrets.token_urlsafe(32)


def write_token(token: str, path: Path | None = None) -> None:
    # Resolve the module-level TOKEN_PATH at call time (not at import time), so tests can
    # monkeypatch autoapply_server.TOKEN_PATH and have it actually take effect.
    target = path if path is not None else TOKEN_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(token, encoding="utf-8")


def read_token(path: Path | None = None) -> str:
    target = path if path is not None else TOKEN_PATH
    return target.read_text(encoding="utf-8").strip()


# ── Candidate pool (fetched once, matched in-process) ──────────────────────────

_candidate_pool_cache: list[dict] | None = None


def get_candidate_pool(force_refresh: bool = False) -> list[dict]:
    """Every row at a status a live-navigated job could still be sitting at, fetched once and
    reused across requests rather than round-tripping Notion on every /plan call."""
    global _candidate_pool_cache
    if _candidate_pool_cache is None or force_refresh:
        pool: list[dict] = []
        for status in CANDIDATE_STATUSES:
            pool.extend(db_get_jobs(status))
        _candidate_pool_cache = pool
    return _candidate_pool_cache


def reset_candidate_pool_cache() -> None:
    global _candidate_pool_cache
    _candidate_pool_cache = None


# ── identify_job() ──────────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Host+path only: query/fragment dropped, job-boards. folded to boards., host lowercased,
    trailing /apply and trailing slash stripped. Deliberately coarse — this is the workhorse
    rung and most real-world duplicates differ only in tracking query params."""
    if not url:
        return ""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.startswith("job-boards."):
        host = "boards." + host[len("job-boards."):]
    path = p.path or ""
    if path.endswith("/apply"):
        path = path[: -len("/apply")]
    path = path.rstrip("/")
    return f"{host}{path}"


def identify_job(pool: list[dict], live_url: str, page_id: str | None = None) -> dict:
    """Whose job is the live page the human is standing on? Never guesses: 2+ matches at any
    rung is reported ambiguous, picking neither, rather than attaching the wrong resume.

    Returns {"status": "known"|"matched"|"ambiguous"|"ask", "page_id", "job", "rung",
    "confidence", "candidates"}. "job"/"page_id" are set only for "known"/"matched".
    """
    # Rung 0 — a launcher-opened tab already knows its own job. Skips every other rung.
    if page_id:
        job = next((c for c in pool if c.get("page_id") == page_id), None)
        return {"status": "known", "page_id": page_id, "job": job, "rung": 0,
                "confidence": "known_page_id", "candidates": []}

    # Rung 1 — normalized URL (exact match is this rung's degenerate case).
    live_norm = normalize_url(live_url)
    rung1 = [c for c in pool if live_norm and normalize_url(c.get("url", "")) == live_norm]
    if len(rung1) == 1:
        job = rung1[0]
        confidence = "exact" if job.get("url") == live_url else "normalized"
        return {"status": "matched", "page_id": job["page_id"], "job": job, "rung": 1,
                "confidence": confidence, "candidates": []}
    if len(rung1) >= 2:
        return {"status": "ambiguous", "page_id": None, "job": None, "rung": 1,
                "confidence": None, "candidates": rung1}

    # Rung 2 — Greenhouse (board_token, job_id), for aggregator links normalization can't fold.
    token, job_id = parse_greenhouse_url(live_url)
    if token and job_id:
        rung2 = [c for c in pool if parse_greenhouse_url(c.get("url", "")) == (token, job_id)]
        if len(rung2) == 1:
            job = rung2[0]
            return {"status": "matched", "page_id": job["page_id"], "job": job, "rung": 2,
                    "confidence": "greenhouse_ids", "candidates": []}
        if len(rung2) >= 2:
            return {"status": "ambiguous", "page_id": None, "job": None, "rung": 2,
                    "confidence": None, "candidates": rung2}

    # Rung 3 — ask. Nothing matched; hand the whole pool to the human.
    return {"status": "ask", "page_id": None, "job": None, "rung": 3,
            "confidence": None, "candidates": pool}


def _job_brief(job: dict) -> dict:
    """Trim a full job dict to what the panel needs to render a candidate/match — never the
    full profile-joined plan data."""
    return {"page_id": job.get("page_id"), "title": job.get("title", ""),
            "company": job.get("company", ""), "url": job.get("url", "")}


# ── _dom_to_schema() — the one genuinely new piece of logic in this project ────

def _dom_to_schema(dom: dict) -> dict:
    """Convert a content-script DOM scrape into the exact schema shape build_application_plan()
    already consumes (Greenhouse's own ?questions=true shape). Kept a pure function (payload
    in, schema dict out) so it unit-diffs against SAMPLE_QUESTIONS (autoapply.py:191) — that
    diff is the proof this bridge adds no answer logic of its own."""
    questions = []
    for q in dom.get("questions", []):
        fields = []
        for f in q.get("fields", []):
            dom_type = (f.get("domType") or "text").lower()
            field = {"name": f.get("name", ""), "type": _DOM_TYPE_MAP.get(dom_type, "input_text")}
            if f.get("options"):
                field["values"] = f["options"]
            fields.append(field)
        questions.append({
            "label": q.get("label", ""), "required": bool(q.get("required")), "fields": fields,
        })
    return {"title": dom.get("title", ""), "questions": questions}


# ── POST /plan ───────────────────────────────────────────────────────────────

def build_plan_response(payload: dict) -> dict:
    """Compose resolve_tailored_resume() + build_application_plan() + readiness_report()
    against the live page's own DOM-scraped schema — see the module docstring for why this
    does not call plan_for_job()."""
    live_url = payload.get("live_url") or payload.get("url") or ""
    page_id = payload.get("page_id")
    dom = payload.get("dom") or {"title": "", "questions": []}

    pool = get_candidate_pool()
    if page_id and not any(c.get("page_id") == page_id for c in pool):
        pool = get_candidate_pool(force_refresh=True)
    match = identify_job(pool, live_url, page_id=page_id)
    job = match.get("job")

    channel = detect_apply_channel(live_url)
    resume_path = resolve_tailored_resume(job) if job else ""

    schema = _dom_to_schema(dom)
    plan = build_application_plan(schema, resume_path=resume_path, schema_known=True)
    if not plan.get("title"):
        plan["title"] = dom.get("title") or (job.get("title") if job else "")

    if channel in _READONLY_CHANNELS:
        for f in plan["fields"]:
            f["status"] = "review_required"
            f["value"] = None
            f["source"] = _READONLY_SOURCE

    rpt = readiness_report(plan)

    return {
        "channel": channel,
        "job_match": {
            "status": match["status"], "page_id": match["page_id"], "rung": match["rung"],
            "confidence": match["confidence"],
            "job": _job_brief(job) if job else None,
            "candidates": [_job_brief(c) for c in match["candidates"]],
        },
        "plan": plan,
        "report": {k: v for k, v in rpt.items() if k not in ("ready", "review", "blocking")},
    }


# ── GET /jobs/ready ───────────────────────────────────────────────────────────

def build_jobs_ready_response() -> dict:
    """The side panel's job-list launcher (step-15h): every job at Status = 'Resume Tailored'
    with no Date Applied, sorted by score desc — exactly db_get_ready_to_apply()'s contract,
    no new Notion query logic here. Trimmed to what the panel renders/needs to open the tab."""
    jobs = db_get_ready_to_apply()
    return {
        "jobs": [
            {
                "page_id": j.get("page_id"),
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "url": j.get("url", ""),
                "score": j.get("ats_score"),
                "tailored_resume_link": j.get("resume_link", ""),
            }
            for j in jobs
        ]
    }


# ── GET /resume/meta ─────────────────────────────────────────────────────────

def build_resume_meta_response(page_id: str) -> dict:
    """{filename, size, mime, abs_path} for the matched job's tailored resume — no bytes.
    `GET /resume` with actual bytes is step-15d; this exists so the panel can show
    "will attach: X.docx" and so that story doesn't have to invent this lookup later."""
    pool = get_candidate_pool()
    job = next((c for c in pool if c.get("page_id") == page_id), None)
    if job is None:
        pool = get_candidate_pool(force_refresh=True)
        job = next((c for c in pool if c.get("page_id") == page_id), None)
    if job is None:
        return {"error": "job not found"}

    resume_path = resolve_tailored_resume(job)
    if not resume_path:
        return {"error": "no resume on file for this job"}

    p = Path(resume_path)
    mime = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf":  "application/pdf",
    }.get(p.suffix.lower(), "application/octet-stream")
    return {"filename": p.name, "size": p.stat().st_size, "mime": mime, "abs_path": str(p)}


_MIME_BY_SUFFIX = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf":  "application/pdf",
}


# ── GET /resume ────────────────────────────────────────────────────────────────

def _resolve_within_resumes_dir(resume_path: str) -> Path | None:
    """The hard containment check: the resolved path must sit under RESUMES_DIR, else None.
    resolve_tailored_resume() ultimately traces back to a Notion row's Tailored Resume Link,
    which is user-editable, and this route is the first one a browser (untrusted caller) can
    reach it through — so the resolved path is never trusted without this check."""
    resumes_root = Path(RESUMES_DIR).resolve()
    resolved = Path(resume_path).resolve()
    if resolved == resumes_root or resumes_root in resolved.parents:
        return resolved
    return None


def build_resume_response(page_id: str, accept: str = "", live_url: str = "") -> dict:
    """{bytes, mime, filename} for the tailored resume's actual bytes, or {"error", "status"}.

    Enforces, independent of anything the client claims:
      - read-only channels (LinkedIn/Indeed) get no bytes at all, only /resume/meta;
      - the resolved file must be under RESUMES_DIR (see _resolve_within_resumes_dir);
      - a form whose `accept` attribute rejects .docx gets a converted PDF instead (mirrors
        Layer 2's accepts_docx()/convert_docx_to_pdf() decision), or a clean error if no
        LibreOffice install is available to produce one.
    """
    pool = get_candidate_pool()
    job = next((c for c in pool if c.get("page_id") == page_id), None)
    if job is None:
        pool = get_candidate_pool(force_refresh=True)
        job = next((c for c in pool if c.get("page_id") == page_id), None)
    if job is None:
        return {"error": "job not found", "status": HTTPStatus.NOT_FOUND}

    channel = detect_apply_channel(live_url or job.get("url", ""))
    if channel in _READONLY_CHANNELS:
        return {"error": _READONLY_SOURCE, "status": HTTPStatus.FORBIDDEN}

    resume_path = resolve_tailored_resume(job)
    if not resume_path:
        return {"error": "no resume on file for this job", "status": HTTPStatus.NOT_FOUND}

    resolved = _resolve_within_resumes_dir(resume_path)
    if resolved is None:
        return {"error": "resume path outside RESUMES_DIR", "status": HTTPStatus.FORBIDDEN}

    serve_path = resolved
    if not accepts_docx(accept) and serve_path.suffix.lower() == ".docx":
        converted = convert_docx_to_pdf(str(serve_path))
        if not converted:
            return {"error": "form requires a format this resume can't be converted to",
                    "status": HTTPStatus.CONFLICT}
        serve_path = Path(converted)

    mime = _MIME_BY_SUFFIX.get(serve_path.suffix.lower(), "application/octet-stream")
    return {"bytes": serve_path.read_bytes(), "mime": mime, "filename": serve_path.name,
            "status": HTTPStatus.OK}


# ── HTTP handler ───────────────────────────────────────────────────────────────

def make_handler(token: str, routes: dict | None = None):
    """Build a BaseHTTPRequestHandler subclass closed over this server instance's token.

    `routes` lets tests register extra stub GET routes (path -> (status, body_dict)) to exercise
    the auth-check plumbing independent of the real authed routes below.
    """
    routes = dict(routes or {})

    class Handler(BaseHTTPRequestHandler):
        # Quiet the default per-request stderr logging; this is a local dev tool, not a service.
        def log_message(self, fmt, *args):
            pass

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            origin = self.headers.get("Origin")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, body: bytes, mime: str, filename: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            origin = self.headers.get("Origin")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            auth = self.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            return secrets.compare_digest(auth, expected)

        def do_OPTIONS(self):
            self._send_json(HTTPStatus.NO_CONTENT, {})

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return

            if path == "/jobs/ready":
                if not self._authed():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid or missing token"})
                    return
                self._send_json(HTTPStatus.OK, build_jobs_ready_response())
                return

            if path == "/resume/meta":
                if not self._authed():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid or missing token"})
                    return
                page_id = (parse_qs(parsed.query).get("page_id") or [None])[0]
                if not page_id:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "page_id required"})
                    return
                result = build_resume_meta_response(page_id)
                self._send_json(
                    HTTPStatus.NOT_FOUND if "error" in result else HTTPStatus.OK, result)
                return

            if path == "/resume":
                if not self._authed():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid or missing token"})
                    return
                qs = parse_qs(parsed.query)
                page_id = (qs.get("page_id") or [None])[0]
                if not page_id:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "page_id required"})
                    return
                accept = (qs.get("accept") or [""])[0]
                live_url = (qs.get("live_url") or [""])[0]
                result = build_resume_response(page_id, accept=accept, live_url=live_url)
                if "error" in result:
                    self._send_json(result["status"], {"error": result["error"]})
                    return
                self._send_file(result["bytes"], result["mime"], result["filename"])
                return

            if path in routes:
                if path not in UNAUTHED_PATHS and not self._authed():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid or missing token"})
                    return
                status, payload = routes[path]
                self._send_json(status, payload)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/plan":
                if not self._authed():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid or missing token"})
                    return
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
                    return
                self._send_json(HTTPStatus.OK, build_plan_response(payload))
                return

            if path in routes:
                if path not in UNAUTHED_PATHS and not self._authed():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid or missing token"})
                    return
                status, payload = routes[path]
                self._send_json(status, payload)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


class _Server(ThreadingHTTPServer):
    # SO_REUSEADDR off: on POSIX this makes a second bind on an already-listening port fail
    # loudly (step-15a's verification item 5) instead of silently colliding.
    allow_reuse_address = False


def serve(port: int = DEFAULT_PORT, routes: dict | None = None) -> ThreadingHTTPServer:
    """Start the bridge and return the (already-bound) server. Caller runs serve_forever()."""
    token = generate_token()
    write_token(token)
    handler = make_handler(token, routes=routes)
    # Bind literal "127.0.0.1" — never "" (which binds all interfaces).
    httpd = _Server(("127.0.0.1", port), handler)
    return httpd


def run_forever(port: int = DEFAULT_PORT) -> None:
    httpd = serve(port=port)
    print(f"🌉 Bridge listening on http://127.0.0.1:{port}  (token: {TOKEN_PATH})")
    print("   GET /health — no auth required")
    print("   Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_forever()
