#!/usr/bin/env python3
"""
tests/record_ai_responses.py — Phase 3a: real-call recording pass (manual, not part of CI).

Runs the actual stage 1/2/3 AI-call functions against realistic and adversarial inputs
through the Claude Code subscription (AI_PROVIDER="claude_code" — free under the
subscription, no metered API key touched) and saves each raw response under
tests/fixtures/recorded_ai_responses/. Phase 3b's mocked contract tests replay these
recordings instead of hand-authored canned JSON, so they're seeded from what a real model
actually does under batch/near-truncation prompts (see the 2026-07-16 incident writeup in
docs/backlog/step-9-evals-testing.md) instead of imagined well-formed responses.

This script is NEVER invoked by run.py, tests.yml, or nightly-pipeline.yml. Run it by hand,
manually, whenever a prompt or chunk size changes meaningfully enough that stale fixtures
would stop reflecting real model behavior:

    python tests/record_ai_responses.py                  # all scenarios
    python tests/record_ai_responses.py --only stage1     # one module's scenarios
    python tests/record_ai_responses.py --list            # list scenario names, don't run

Requires the Claude Code CLI installed and logged in (`claude /login`). Does not require
ANTHROPIC_API_KEY / NOTION_API_KEY / APIFY_API_TOKEN.
"""
import argparse
import datetime
import functools
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Force the subscription provider on both tiers for this process only, before config.settings
# (and anything importing it) is loaded — same mechanism run.py's --ai-mode subscription uses.
os.environ["FAST_PROVIDER"] = "claude_code"
os.environ["QUALITY_PROVIDER"] = "claude_code"

FIXTURES_DIR = ROOT / "tests" / "fixtures" / "recorded_ai_responses"


# ── Recording plumbing ────────────────────────────────────────────────────

def _record_call(module, attr_name: str, sink: list):
    """Wrap module.<attr_name> so every real call's raw response is appended to `sink`,
    then still returns it to the caller unchanged. Must patch the *stage module's* own
    bound name (not scripts.utils) — see tests/conftest.py's note on direct-name imports."""
    original = getattr(module, attr_name)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        raw = original(*args, **kwargs)
        sink.append(raw)
        return raw

    setattr(module, attr_name, wrapper)
    return original


def _restore_call(module, attr_name: str, original):
    setattr(module, attr_name, original)


def _save_fixture(subdir: str, name: str, *, scenario: str, function: str,
                   input_summary: dict, raw_response: str, provider: str, model: str):
    from scripts.utils import parse_json_response

    parse_error = None
    parsed_ok = True
    try:
        parse_json_response(raw_response)
    except Exception as exc:
        parsed_ok = False
        parse_error = str(exc)

    out_dir = FIXTURES_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": scenario,
        "function": function,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "input_summary": input_summary,
        "raw_response": raw_response,
        "parse_success": parsed_ok,
        "parse_error": parse_error,
    }
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    status = "parsed OK" if parsed_ok else f"PARSE FAILED ({parse_error})"
    print(f"  saved {path.relative_to(ROOT)}  [{status}, {len(raw_response)} chars]")


# ── Job/resume fixtures ────────────────────────────────────────────────────

SAMPLE_RESUME = (
    "Krishna Achyuth — Senior Software Engineer\n"
    "Skills: Python, JavaScript, React, Node.js, AWS, Docker, Kubernetes, PostgreSQL, "
    "REST APIs, microservices, CI/CD.\n"
    "Experience: 6 years building backend and full-stack systems at scale; led migration "
    "of a monolith to microservices; owns on-call for a payments service processing "
    "millions of transactions/day.\n"
)

_TITLES = [
    "Senior Backend Engineer", "Staff Software Engineer", "Full-Stack Engineer",
    "Platform Engineer", "Senior Software Engineer, Infrastructure", "Backend Engineer II",
    "Software Engineer, Distributed Systems", "Senior Cloud Engineer",
]
_COMPANIES = [
    "Acme Corp", "Beta Inc", "Gamma LLC", "Delta Systems", "Epsilon Labs", "Zeta Cloud",
    "Theta Analytics", "Iota Networks", "Kappa Technologies", "Lambda Software",
]


def make_jobs(n: int) -> list[dict]:
    jobs = []
    for i in range(n):
        title = _TITLES[i % len(_TITLES)]
        company = f"{_COMPANIES[i % len(_COMPANIES)]} {i // len(_COMPANIES) or ''}".strip()
        jobs.append({
            "url": f"https://example.com/jobs/{i}",
            "title": title,
            "company": company,
            "location": "Remote - US",
            "description": (
                f"We are hiring a {title} at {company}. Looking for experience with "
                "Python, AWS, Kubernetes, PostgreSQL, and distributed systems. "
                "Must be authorized to work in the US."
            ),
            "applicant_count": 10 + i,
            "salary_range": "$140,000 - $190,000",
        })
    return jobs


SAMPLE_JOB = make_jobs(1)[0]


# ── Stage 1 scenarios: score_jobs_batch / _score_jobs_chunk ───────────────

def scenario_stage1_batches():
    import scripts.stage1_scrape as stage1

    for n in (1, 20, 21, 50, 100):
        jobs = make_jobs(n)
        sink = []
        orig = _record_call(stage1, "claude_chat", sink)
        try:
            stage1.score_jobs_batch(jobs, SAMPLE_RESUME)
        finally:
            _restore_call(stage1, "claude_chat", orig)
        # One recording per underlying chunk call this batch size produced.
        for i, raw in enumerate(sink):
            suffix = f"_chunk{i}" if len(sink) > 1 else ""
            _save_fixture(
                "stage1_score", f"batch_{n:03d}{suffix}",
                scenario=f"score_jobs_batch, {n} job(s), chunk {i}/{len(sink)}",
                function="score_jobs_batch/_score_jobs_chunk",
                input_summary={"job_count": n, "chunk_index": i, "chunk_count": len(sink)},
                raw_response=raw, provider="claude_code", model="sonnet",
            )


def scenario_stage1_oversized_single_call():
    """Bypass score_jobs_batch's chunking entirely and call _score_jobs_chunk directly with
    150 jobs in ONE call — reproduces the 2026-07-16 incident's shape (one oversized call)
    directly, rather than trusting the _SCORE_CHUNK_SIZE fix in isolation."""
    import scripts.stage1_scrape as stage1

    jobs = make_jobs(150)
    sink = []
    orig = _record_call(stage1, "claude_chat", sink)
    try:
        stage1._score_jobs_chunk(jobs, SAMPLE_RESUME)
    finally:
        _restore_call(stage1, "claude_chat", orig)
    _save_fixture(
        "stage1_score", "oversized_single_call_150",
        scenario="_score_jobs_chunk called directly with 150 jobs (no chunking) — "
                 "truncation repro for the 2026-07-16 incident",
        function="_score_jobs_chunk",
        input_summary={"job_count": 150, "chunked": False},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


def scenario_stage1_empty_garbled_description():
    import scripts.stage1_scrape as stage1

    jobs = [
        {**SAMPLE_JOB, "url": "https://example.com/jobs/empty-desc", "description": ""},
        {**SAMPLE_JOB, "url": "https://example.com/jobs/garbled-desc",
         "description": "�☒☒ ###//\\\\ null null undefined <<<>>> {{}} ??!!"},
    ]
    sink = []
    orig = _record_call(stage1, "claude_chat", sink)
    try:
        stage1.score_jobs_batch(jobs, SAMPLE_RESUME)
    finally:
        _restore_call(stage1, "claude_chat", orig)
    _save_fixture(
        "stage1_score", "empty_garbled_description",
        scenario="one empty JD + one garbled/non-language JD in the same chunk",
        function="score_jobs_batch/_score_jobs_chunk",
        input_summary={"job_count": len(jobs)},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


# ── Stage 2 scenarios: _tailor_resume_single / tailor_resumes_batch ───────

def scenario_stage2_single_normal():
    import scripts.stage2_tailor as stage2

    job = {**SAMPLE_JOB, "missing_keywords": ["Terraform", "GraphQL"]}
    sink = []
    orig = _record_call(stage2, "ai_chat_blocks", sink)
    try:
        stage2._tailor_resume_single(SAMPLE_RESUME, job["description"], job)
    finally:
        _restore_call(stage2, "ai_chat_blocks", orig)
    _save_fixture(
        "stage2_tailor", "single_normal",
        scenario="_tailor_resume_single, normal-size missing_keywords hint",
        function="_tailor_resume_single",
        input_summary={"missing_keywords_count": len(job["missing_keywords"])},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


def scenario_stage2_huge_keyword_hint():
    import scripts.stage2_tailor as stage2

    huge_keywords = [f"keyword_{i}" for i in range(80)]
    job = {**SAMPLE_JOB, "missing_keywords": huge_keywords}
    sink = []
    orig = _record_call(stage2, "ai_chat_blocks", sink)
    try:
        stage2._tailor_resume_single(SAMPLE_RESUME, job["description"], job)
    finally:
        _restore_call(stage2, "ai_chat_blocks", orig)
    _save_fixture(
        "stage2_tailor", "single_huge_keyword_hint",
        scenario="_tailor_resume_single with an intentionally huge (80-entry) "
                 "missing_keywords hint list",
        function="_tailor_resume_single",
        input_summary={"missing_keywords_count": len(huge_keywords)},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


def scenario_stage2_batch_normal():
    import scripts.stage2_tailor as stage2

    jobs = make_jobs(3)
    jobs_and_jds = [(j, j["description"]) for j in jobs]
    sink = []
    orig = _record_call(stage2, "ai_chat_blocks", sink)
    try:
        stage2.tailor_resumes_batch(SAMPLE_RESUME, jobs_and_jds)
    finally:
        _restore_call(stage2, "ai_chat_blocks", orig)
    _save_fixture(
        "stage2_tailor", "batch_normal_3jobs",
        scenario="tailor_resumes_batch, 3 jobs in one call",
        function="tailor_resumes_batch",
        input_summary={"job_count": 3},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


# ── Stage 3 scenarios: draft_cold_emails_batch / draft_inmail_batch ───────

def scenario_stage3_cold_email_batch():
    import scripts.stage3_outreach as stage3
    from config.settings import YOUR_BIO

    jobs = make_jobs(5)
    sink = []
    orig = _record_call(stage3, "claude_chat", sink)
    try:
        stage3.draft_cold_emails_batch(jobs, YOUR_BIO)
    finally:
        _restore_call(stage3, "claude_chat", orig)
    _save_fixture(
        "stage3_outreach", "cold_email_batch_5",
        scenario="draft_cold_emails_batch, 5 jobs in one call",
        function="draft_cold_emails_batch",
        input_summary={"job_count": 5},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


def scenario_stage3_inmail_batch():
    import scripts.stage3_outreach as stage3
    from config.settings import YOUR_BIO

    jobs = make_jobs(5)
    for j in jobs:
        j["ats_score"] = 85
    sink = []
    orig = _record_call(stage3, "claude_chat", sink)
    try:
        stage3.draft_inmail_batch(jobs, YOUR_BIO)
    finally:
        _restore_call(stage3, "claude_chat", orig)
    _save_fixture(
        "stage3_outreach", "inmail_batch_5",
        scenario="draft_inmail_batch, 5 jobs in one call",
        function="draft_inmail_batch",
        input_summary={"job_count": 5},
        raw_response=sink[0] if sink else "", provider="claude_code", model="sonnet",
    )


SCENARIOS = {
    "stage1_batches":               ("stage1", scenario_stage1_batches),
    "stage1_oversized_single_call": ("stage1", scenario_stage1_oversized_single_call),
    "stage1_empty_garbled":         ("stage1", scenario_stage1_empty_garbled_description),
    "stage2_single_normal":         ("stage2", scenario_stage2_single_normal),
    "stage2_huge_keyword_hint":     ("stage2", scenario_stage2_huge_keyword_hint),
    "stage2_batch_normal":          ("stage2", scenario_stage2_batch_normal),
    "stage3_cold_email_batch":      ("stage3", scenario_stage3_cold_email_batch),
    "stage3_inmail_batch":          ("stage3", scenario_stage3_inmail_batch),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["stage1", "stage2", "stage3"], default=None,
                         help="Run only one stage's scenarios")
    parser.add_argument("--list", action="store_true", help="List scenarios and exit")
    args = parser.parse_args()

    if args.list:
        for name, (group, _) in SCENARIOS.items():
            print(f"{group:8s} {name}")
        return

    to_run = {n: fn for n, (g, fn) in SCENARIOS.items() if not args.only or g == args.only}
    print(f"Recording {len(to_run)} scenario(s) via Claude Code subscription "
          f"(FAST_PROVIDER=QUALITY_PROVIDER=claude_code)...\n")
    for name, fn in to_run.items():
        print(f"-> {name}")
        fn()
    print(f"\nDone. Fixtures under {FIXTURES_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
