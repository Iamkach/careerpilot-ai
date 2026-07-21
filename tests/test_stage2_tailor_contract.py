"""
Phase 3b — mocked AI-flow contract tests for scripts/stage2_tailor.py's tailoring path,
seeded from Phase 3a's real-model recordings (tests/fixtures/recorded_ai_responses/).

Tests the plumbing: tailor_resumes_batch's missing-entry contract (caller falls back to
_tailor_resume_single), a full batch-parse failure, and verify_tailored_score's
empty-result synthesis — not AI judgment quality.
"""
import json

import requests

from scripts import stage2_tailor
from tests.conftest import load_recorded, make_recorded_jobs


# ── fetch_jd HTML stripping ──────────────────────────────────────────────────

class _FakeJDResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_fetch_jd_strips_script_and_style_content(monkeypatch):
    """PR #11 review item #8: fetch_jd() must not leak raw <script>/<style> body text into
    the job description sent to the AI model. It now reuses sources._strip_html(), which
    drops script/style blocks entirely before stripping the remaining tags, instead of a
    second/weaker inline regex that only stripped tags and left their contents behind."""
    html = """
    <html>
      <head>
        <style>.hero { color: red; } body { display: none; }</style>
        <script>var trackingId = "abc123"; function evil() { alert('x'); }</script>
      </head>
      <body>
        <script>console.log("more js that must not leak");</script>
        <h1>Senior Backend Engineer</h1>
        <p>We are looking for an experienced engineer to join our team.</p>
        <style>.footer { font-size: 10px; }</style>
      </body>
    </html>
    """
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeJDResponse(html))

    jd = stage2_tailor.fetch_jd("https://careers.example.com/job/123")

    assert "trackingId" not in jd
    assert "evil" not in jd
    assert "console.log" not in jd
    assert "color: red" not in jd
    assert "font-size" not in jd
    assert "Senior Backend Engineer" in jd
    assert "experienced engineer to join our team" in jd


def test_tailor_resumes_batch_replays_recorded_batch(patch_ai_chat):
    """The recording was made against make_jobs(3) (Acme Corp, Beta Inc, Gamma LLC, in that
    order) — give each a distinct page_id so we can confirm all 3 real entries matched back
    to the right job by index/company, exactly as tailor_resumes_batch does in production."""
    jobs = make_recorded_jobs(3)
    for i, j in enumerate(jobs):
        j["page_id"] = f"p{i+1}"
    jobs_and_jds = [(j, j["description"]) for j in jobs]
    patch_ai_chat(stage2_tailor, response=load_recorded("stage2_tailor", "batch_normal_3jobs"))

    results = stage2_tailor.tailor_resumes_batch("resume text", jobs_and_jds)

    assert set(results.keys()) == {"p1", "p2", "p3"}
    for pid, (edits, keywords) in results.items():
        assert isinstance(edits, list) and len(edits) > 0
        assert isinstance(keywords, list)


def test_tailor_resumes_batch_missing_entry_signals_caller_fallback(monkeypatch, patch_ai_chat):
    """tailor_resumes_batch's docstring contract: 'Missing entries mean parse failed —
    caller falls back to _tailor_resume_single().' Simulate a response that only covers 2 of
    3 jobs and confirm the 3rd's page_id is absent from the returned dict."""
    jobs = [
        {**make_recorded_jobs(1)[0], "page_id": "p1", "company": "Acme Corp"},
        {**make_recorded_jobs(1)[0], "page_id": "p2", "company": "Beta Inc"},
        {**make_recorded_jobs(1)[0], "page_id": "p3", "company": "Gamma LLC"},
    ]
    jobs_and_jds = [(j, j["description"]) for j in jobs]
    canned = [
        {"job_index": 1, "company": "Acme Corp", "keywords_injected": ["k1"],
         "edits": [{"old": "x", "new": "y", "reason": "r"}]},
        {"job_index": 2, "company": "Beta Inc", "keywords_injected": ["k2"],
         "edits": [{"old": "x", "new": "y", "reason": "r"}]},
        # job 3 (Gamma LLC) missing entirely from the response
    ]
    patch_ai_chat(stage2_tailor, response=json.dumps(canned))

    results = stage2_tailor.tailor_resumes_batch("resume text", jobs_and_jds)

    assert "p1" in results
    assert "p2" in results
    assert "p3" not in results  # caller must fall back to _tailor_resume_single for this one


def test_tailor_resumes_batch_same_company_does_not_cross_assign(patch_ai_chat):
    """Two Reviewed jobs at the same company must never receive each other's edits. Simulate a
    response where neither entry's job_index lines up with its job's position — before the fix,
    the company-keyed fallback silently handed both jobs the same (wrong) entry."""
    jobs = [
        {**make_recorded_jobs(1)[0], "page_id": "p1", "company": "Acme Corp"},
        {**make_recorded_jobs(1)[0], "page_id": "p2", "company": "Acme Corp"},
    ]
    jobs_and_jds = [(j, j["description"]) for j in jobs]
    canned = [
        {"job_index": 5, "company": "Acme Corp", "keywords_injected": ["kA"],
         "edits": [{"old": "x", "new": "role-A-edit", "reason": "r"}]},
        {"company": "Acme Corp", "keywords_injected": ["kB"],
         "edits": [{"old": "x", "new": "role-B-edit", "reason": "r"}]},
    ]
    patch_ai_chat(stage2_tailor, response=json.dumps(canned))

    results = stage2_tailor.tailor_resumes_batch("resume text", jobs_and_jds)

    # Neither job can be safely matched (ambiguous company, no reliable index) — both must be
    # left out so the caller's per-job fallback handles them individually, rather than both
    # silently receiving the same wrong entry.
    assert "p1" not in results
    assert "p2" not in results


def test_tailor_resumes_batch_full_parse_failure_returns_empty_dict(patch_ai_chat):
    """A response that isn't parseable JSON at all must not raise — tailor_resumes_batch
    returns {} so every job falls back to the per-job single-call path."""
    jobs = make_recorded_jobs(2)
    jobs_and_jds = [(j, j["description"]) for j in jobs]
    patch_ai_chat(stage2_tailor, response="Sorry, I can't help with that right now.")

    results = stage2_tailor.tailor_resumes_batch("resume text", jobs_and_jds)

    assert results == {}


def test_tailor_resume_single_replays_recorded_huge_keyword_hint(patch_ai_chat):
    """_tailor_resume_single with an intentionally huge (80-entry) missing_keywords hint —
    confirms the batch-to-single fallback path still returns a well-formed (edits, keywords)
    pair for a stress-sized hint list, matching what a real model actually returned."""
    huge_keywords = [f"keyword_{i}" for i in range(80)]
    job = {**make_recorded_jobs(1)[0], "missing_keywords": huge_keywords}
    patch_ai_chat(stage2_tailor, response=load_recorded("stage2_tailor", "single_huge_keyword_hint"))

    edits, keywords = stage2_tailor._tailor_resume_single("resume text", job["description"], job)

    assert isinstance(edits, list)
    assert isinstance(keywords, list)
    assert len(edits) > 0
    for e in edits:
        assert "old" in e and "new" in e


def test_tailor_resume_single_non_dict_json_returns_empty_lists(patch_ai_chat):
    """Contract: valid JSON that parses to something other than a dict (e.g. a bare array)
    returns ([], []) rather than raising — the caller applies zero edits and moves on."""
    job = make_recorded_jobs(1)[0]
    patch_ai_chat(stage2_tailor, response="[1, 2, 3]")

    edits, keywords = stage2_tailor._tailor_resume_single("resume text", job["description"], job)

    assert edits == []
    assert keywords == []


def test_tailor_resume_single_unparseable_json_raises(patch_ai_chat):
    """Characterization test, not a bug fix: unlike tailor_resumes_batch (which wraps its
    parse in try/except and returns {} on failure), _tailor_resume_single has no such guard —
    a response parse_json_response can't recover JSON from propagates a ValueError straight
    up to the caller. Since run()'s batch-to-single fallback loop doesn't catch this either,
    one malformed single-job fallback response currently aborts the rest of stage 2's run."""
    job = make_recorded_jobs(1)[0]
    patch_ai_chat(stage2_tailor, response="not json at all")

    try:
        stage2_tailor._tailor_resume_single("resume text", job["description"], job)
        assert False, "expected parse_json_response's ValueError to propagate"
    except ValueError:
        pass


# ── verify_tailored_score empty-result synthesis ────────────────────────────

def test_verify_tailored_score_synthesizes_unscored_on_empty_result(monkeypatch):
    """score_jobs_batch() can return [] (e.g. jobs=[] short-circuit, or the URL never made it
    into the parsed response) — verify_tailored_score must synthesize the documented
    {url, score: None, scored: False} shape rather than raising an IndexError."""
    job = make_recorded_jobs(1)[0]
    monkeypatch.setattr(stage2_tailor, "score_jobs_batch", lambda jobs, resume: [])

    result = stage2_tailor.verify_tailored_score("tailored resume text", job["description"], job)

    assert result == {"url": job["url"], "score": None, "scored": False}


def test_verify_tailored_score_passes_through_a_real_scored_result(monkeypatch):
    job = make_recorded_jobs(1)[0]
    canned = {"url": job["url"], "score": 91, "scored": True, "missing_keywords": [],
              "sponsorship": "unknown", "company_type": "product"}
    monkeypatch.setattr(stage2_tailor, "score_jobs_batch", lambda jobs, resume: [canned])

    result = stage2_tailor.verify_tailored_score("tailored resume text", job["description"], job)

    assert result == canned
