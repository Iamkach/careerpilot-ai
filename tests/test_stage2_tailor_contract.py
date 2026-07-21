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


# ── verify_tailored_scores_batch (PR #11 review item 9: batch, don't call once per job) ──

def _verify_job(company="Acme Corp", page_id="p1", url=None):
    return {
        "page_id": page_id, "url": url or f"https://example.com/{page_id}",
        "title": "Backend Engineer", "company": company, "ats_score": 60,
    }


def test_verify_tailored_scores_batch_one_ai_call_for_multiple_jobs(patch_ai_chat):
    """The whole point of the fix: N jobs must cost ONE AI call, not N."""
    jobs = [_verify_job(page_id=f"p{i+1}", company=f"Company{i+1}") for i in range(3)]
    canned = [
        {"job_index": i + 1, "company": job["company"], "score": 70 + i,
         "missing_keywords": ["k"], "sponsorship": "unknown", "company_type": "product"}
        for i, job in enumerate(jobs)
    ]
    fake = patch_ai_chat(stage2_tailor, response=json.dumps(canned))

    jobs_and_tailored = [(job, f"tailored text {job['page_id']}", "jd text") for job in jobs]
    results = stage2_tailor.verify_tailored_scores_batch(jobs_and_tailored)

    assert len(fake.calls) == 1  # one AI call total, regardless of job count
    assert set(results.keys()) == {"p1", "p2", "p3"}
    assert results["p1"]["score"] == 70
    assert results["p2"]["score"] == 71
    assert results["p3"]["score"] == 72
    for r in results.values():
        assert r["scored"] is True


def test_verify_tailored_scores_batch_empty_input_returns_empty_without_ai_call(patch_ai_chat):
    fake = patch_ai_chat(stage2_tailor, response="[]")

    results = stage2_tailor.verify_tailored_scores_batch([])

    assert results == {}
    assert len(fake.calls) == 0


def test_verify_tailored_scores_batch_missing_entry_signals_caller_fallback(patch_ai_chat):
    jobs = [_verify_job(page_id="p1", company="Acme Corp"),
            _verify_job(page_id="p2", company="Beta Inc"),
            _verify_job(page_id="p3", company="Gamma LLC")]
    canned = [
        {"job_index": 1, "company": "Acme Corp", "score": 80, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"},
        {"job_index": 2, "company": "Beta Inc", "score": 82, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"},
        # job 3 (Gamma LLC) missing entirely from the response
    ]
    patch_ai_chat(stage2_tailor, response=json.dumps(canned))

    jobs_and_tailored = [(job, "tailored text", "jd text") for job in jobs]
    results = stage2_tailor.verify_tailored_scores_batch(jobs_and_tailored)

    assert "p1" in results
    assert "p2" in results
    assert "p3" not in results  # caller must fall back to verify_tailored_score for this one


def test_verify_tailored_scores_batch_same_company_does_not_cross_assign(patch_ai_chat):
    jobs = [_verify_job(page_id="p1", company="Acme Corp"),
            _verify_job(page_id="p2", company="Acme Corp")]
    canned = [
        {"job_index": 5, "company": "Acme Corp", "score": 90, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"},
        {"company": "Acme Corp", "score": 40, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"},
    ]
    patch_ai_chat(stage2_tailor, response=json.dumps(canned))

    jobs_and_tailored = [(job, "tailored text", "jd text") for job in jobs]
    results = stage2_tailor.verify_tailored_scores_batch(jobs_and_tailored)

    assert "p1" not in results
    assert "p2" not in results


def test_verify_tailored_scores_batch_full_parse_failure_returns_empty_dict(patch_ai_chat):
    jobs = [_verify_job(page_id="p1"), _verify_job(page_id="p2", company="Beta Inc")]
    patch_ai_chat(stage2_tailor, response="Sorry, I can't help with that right now.")

    jobs_and_tailored = [(job, "tailored text", "jd text") for job in jobs]
    results = stage2_tailor.verify_tailored_scores_batch(jobs_and_tailored)

    assert results == {}


def test_verify_tailored_scores_batch_clamps_score_and_normalizes_enums(patch_ai_chat):
    job = _verify_job(page_id="p1")
    canned = [{"job_index": 1, "company": "Acme Corp", "score": 500,
               "missing_keywords": ["x"], "sponsorship": "maybe", "company_type": "bogus"}]
    patch_ai_chat(stage2_tailor, response=json.dumps(canned))

    results = stage2_tailor.verify_tailored_scores_batch([(job, "tailored text", "jd text")])

    assert results["p1"]["score"] == 100  # clamped to 0-100
    assert results["p1"]["sponsorship"] == "unknown"
    assert results["p1"]["company_type"] == "unknown"


def test_verify_tailored_scores_batch_chunks_large_job_lists(patch_ai_chat, monkeypatch):
    """More than _VERIFY_CHUNK_SIZE jobs must still cost multiple bounded calls (one per
    chunk), never one unbounded call — mirrors stage 1's score_jobs_batch chunking."""
    monkeypatch.setattr(stage2_tailor, "_VERIFY_CHUNK_SIZE", 2)
    jobs = [_verify_job(page_id=f"p{i+1}", company=f"Company{i+1}") for i in range(5)]

    def _canned_for_chunk(prompt, system="", max_tokens=4096, quality=False):
        # Echo back an entry for every job_index the chunk's prompt actually asked about.
        import re
        indices = sorted({int(m) for m in re.findall(r"^(\d+)\. Company:", prompt, re.M)})
        return json.dumps([
            {"job_index": idx, "company": f"Company{idx}", "score": 50, "missing_keywords": [],
             "sponsorship": "unknown", "company_type": "product"}
            for idx in indices
        ])

    fake = patch_ai_chat(stage2_tailor)
    fake.set_responses([
        _canned_for_chunk("1. Company: Company1\n2. Company: Company2"),
        _canned_for_chunk("1. Company: Company1\n2. Company: Company2"),
        _canned_for_chunk("1. Company: Company1"),
    ])

    jobs_and_tailored = [(job, "tailored text", "jd text") for job in jobs]
    results = stage2_tailor.verify_tailored_scores_batch(jobs_and_tailored)

    assert len(fake.calls) == 3  # ceil(5 / 2) chunks
    assert set(results.keys()) == {"p1", "p2", "p3", "p4", "p5"}


# ── run()'s Phase 3/4/5: batched verification, not one call per job ──────────

def _stub_run_dependencies(monkeypatch, jobs, description="Some JD text"):
    """Wire run() up to fakes for everything except the two functions under test
    (verify_tailored_scores_batch / verify_tailored_score), so a run() test can assert
    call counts on those without touching real Notion, AI, or .docx I/O."""
    monkeypatch.setattr(stage2_tailor, "load_base_resume_text", lambda: "BASE RESUME")
    monkeypatch.setattr(stage2_tailor, "get_reviewed_jobs", lambda min_score=0: jobs)
    monkeypatch.setattr(stage2_tailor, "_sponsorship_gate", lambda js: js)
    monkeypatch.setattr(stage2_tailor, "db_get_job_description", lambda pid: description)
    # Non-empty edits so these verify-batching tests don't also trip the zero-edit
    # "Human Review" gate (tested separately in tests/test_stage2_zero_edit_gate.py) —
    # every job here should land on "Resume Tailored" per the assertions below.
    monkeypatch.setattr(
        stage2_tailor, "tailor_resumes_batch",
        lambda resume_text, jobs_and_jds: {
            (j.get("page_id") or j.get("id")): ([{"old": "x", "new": "y", "reason": "r"}], [])
            for j, _ in jobs_and_jds
        },
    )
    monkeypatch.setattr(stage2_tailor, "save_resume", lambda edits, job, resume_text: f"/fake/{job['page_id']}.docx")
    monkeypatch.setattr(stage2_tailor, "extract_docx_text", lambda path: f"tailored text for {path}")

    updates: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        stage2_tailor, "db_update_status",
        lambda page_id, status, extra=None: updates.append((page_id, status, extra or {})),
    )
    return updates


def test_run_verifies_all_tailored_jobs_in_one_batch_call(monkeypatch):
    jobs = [_verify_job(page_id=f"p{i+1}", company=f"Company{i+1}") for i in range(3)]
    _stub_run_dependencies(monkeypatch, jobs)

    batch_calls = []
    single_calls = []

    def _fake_batch(jobs_and_tailored):
        batch_calls.append(len(jobs_and_tailored))
        return {
            (job.get("page_id") or job.get("id")): {
                "url": job["url"], "score": 80, "scored": True,
                "missing_keywords": [], "sponsorship": "unknown", "company_type": "product",
            }
            for job, _, _ in jobs_and_tailored
        }

    def _fake_single(tailored_text, jd, job):
        single_calls.append(job["page_id"])
        return {"url": job["url"], "score": 80, "scored": True}

    monkeypatch.setattr(stage2_tailor, "verify_tailored_scores_batch", _fake_batch)
    monkeypatch.setattr(stage2_tailor, "verify_tailored_score", _fake_single)

    stage2_tailor.run(min_score=0)

    assert batch_calls == [3]  # one batch call covering all 3 jobs
    assert single_calls == []  # no per-job fallback needed — nothing missing from the batch


def test_run_falls_back_to_single_verify_for_job_missing_from_batch(monkeypatch):
    jobs = [_verify_job(page_id=f"p{i+1}", company=f"Company{i+1}") for i in range(3)]
    updates = _stub_run_dependencies(monkeypatch, jobs)

    batch_calls = []
    single_calls = []

    def _fake_batch(jobs_and_tailored):
        batch_calls.append(len(jobs_and_tailored))
        # p3 is missing from the batch response, same as a real parse gap.
        return {
            (job.get("page_id") or job.get("id")): {
                "url": job["url"], "score": 80, "scored": True,
                "missing_keywords": [], "sponsorship": "unknown", "company_type": "product",
            }
            for job, _, _ in jobs_and_tailored if job["page_id"] != "p3"
        }

    def _fake_single(tailored_text, jd, job):
        single_calls.append(job["page_id"])
        return {"url": job["url"], "score": 55, "scored": True}

    monkeypatch.setattr(stage2_tailor, "verify_tailored_scores_batch", _fake_batch)
    monkeypatch.setattr(stage2_tailor, "verify_tailored_score", _fake_single)

    stage2_tailor.run(min_score=0)

    assert batch_calls == [3]
    assert single_calls == ["p3"]  # only the missing job falls back, not all 3
    # every job (including the fallback one) still gets its Notion status updated
    assert {u[0] for u in updates} == {"p1", "p2", "p3"}
    assert all(u[1] == "Resume Tailored" for u in updates)


def test_run_logs_ats_before_after_and_low_score_warning(monkeypatch):
    job = _verify_job(page_id="p1", company="Acme Corp")
    job["ats_score"] = 60
    _stub_run_dependencies(monkeypatch, [job])

    monkeypatch.setattr(
        stage2_tailor, "verify_tailored_scores_batch",
        lambda jobs_and_tailored: {
            "p1": {"url": job["url"], "score": 65, "scored": True,
                   "missing_keywords": [], "sponsorship": "unknown", "company_type": "product"}
        },
    )

    logs: list[str] = []
    monkeypatch.setattr(stage2_tailor, "log", lambda msg: logs.append(msg))

    stage2_tailor.run(min_score=0)

    joined = "\n".join(logs)
    assert "ATS: 60 → 65" in joined  # before → after, preserved from the old per-job loop
    assert "below MIN_TAILORED_ATS_SCORE" in joined  # 65 < default 75


def test_run_logs_verification_failure_when_scoring_unscored(monkeypatch):
    job = _verify_job(page_id="p1", company="Acme Corp")
    _stub_run_dependencies(monkeypatch, [job])

    monkeypatch.setattr(stage2_tailor, "verify_tailored_scores_batch", lambda jobs_and_tailored: {})
    monkeypatch.setattr(stage2_tailor, "verify_tailored_score",
                         lambda tailored_text, jd, job: {"url": job["url"], "score": None, "scored": False})

    logs: list[str] = []
    monkeypatch.setattr(stage2_tailor, "log", lambda msg: logs.append(msg))

    stage2_tailor.run(min_score=0)

    joined = "\n".join(logs)
    assert "Post-tailor verification scoring failed" in joined
