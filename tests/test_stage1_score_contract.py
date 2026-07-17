"""
Phase 3b — mocked AI-flow contract tests for scripts/stage1_scrape.py's scoring path,
seeded from Phase 3a's real-model recordings (tests/fixtures/recorded_ai_responses/).

These test the plumbing around score_jobs_batch/_score_jobs_chunk — chunk boundaries, the
"never fabricate a score" contract, and the chunk-isolation regression from the 2026-07-16
incident (docs/backlog/step-9-evals-testing.md) — not AI judgment quality.
"""
import json

from scripts import stage1_scrape
from tests.conftest import load_recorded, make_recorded_jobs


def test_score_jobs_batch_replays_recorded_single_job(patch_ai_chat):
    """A single job stays in one chunk; the recorded response scores it."""
    jobs = make_recorded_jobs(1)
    patch_ai_chat(stage1_scrape, response=load_recorded("stage1_score", "batch_001"))

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(results) == 1
    assert results[0]["url"] == jobs[0]["url"]
    assert results[0]["scored"] is True
    assert isinstance(results[0]["score"], int)
    assert results[0]["sponsorship"] in ("yes", "no", "unknown")
    assert results[0]["company_type"] in stage1_scrape._COMPANY_TYPES


def test_score_jobs_batch_replays_recorded_exact_chunk_boundary(patch_ai_chat):
    """20 jobs == _SCORE_CHUNK_SIZE exactly: one chunk, one AI call."""
    jobs = make_recorded_jobs(20)
    fake = patch_ai_chat(stage1_scrape, response=load_recorded("stage1_score", "batch_020"))

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(fake.calls) == 1
    assert len(results) == 20
    assert {r["url"] for r in results} == {j["url"] for j in jobs}
    assert all(r["scored"] for r in results)


def test_score_jobs_batch_replays_recorded_21_jobs_splits_into_two_chunks(patch_ai_chat):
    """21 jobs crosses the _SCORE_CHUNK_SIZE=20 boundary: two AI calls, 20 + 1."""
    jobs = make_recorded_jobs(21)
    fake = patch_ai_chat(stage1_scrape, responses=[
        load_recorded("stage1_score", "batch_021_chunk0"),
        load_recorded("stage1_score", "batch_021_chunk1"),
    ])

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(fake.calls) == 2
    assert len(results) == 21
    assert all(r["scored"] for r in results)
    assert {r["url"] for r in results} == {j["url"] for j in jobs}


def test_score_jobs_batch_replays_recorded_50_jobs_three_chunks(patch_ai_chat):
    jobs = make_recorded_jobs(50)
    fake = patch_ai_chat(stage1_scrape, responses=[
        load_recorded("stage1_score", "batch_050_chunk0"),
        load_recorded("stage1_score", "batch_050_chunk1"),
        load_recorded("stage1_score", "batch_050_chunk2"),
    ])

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(fake.calls) == 3
    assert len(results) == 50
    assert all(r["scored"] for r in results)


def test_score_jobs_batch_empty_and_garbled_description_still_returns_a_result(patch_ai_chat):
    """A blank JD and a garbled/non-language JD must never crash scoring — the model still
    returns entries for both URLs (possibly low-confidence scores), not an exception."""
    jobs = [
        {**make_recorded_jobs(1)[0], "url": "https://example.com/jobs/empty-desc", "description": ""},
        {**make_recorded_jobs(1)[0], "url": "https://example.com/jobs/garbled-desc",
         "description": "�☒☒ ###//\\\\ null null undefined <<<>>> {{}} ??!!"},
    ]
    patch_ai_chat(stage1_scrape, response=load_recorded("stage1_score", "empty_garbled_description"))

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(results) == 2
    for r in results:
        # Never crashes; either a real scored entry or the documented unscored shape —
        # never a fabricated score outside that contract.
        assert r["scored"] in (True, False)
        if not r["scored"]:
            assert r["score"] is None


# ── Chunk-isolation regression (2026-07-16 incident) ───────────────────────
#
# _score_jobs_chunk's own try/except (not score_jobs_batch) is what scopes a failure to one
# chunk: score_jobs_batch itself has no try/except around each _score_jobs_chunk() call, so
# isolation only holds because _score_jobs_chunk never lets an ai_chat/parse exception escape
# — it catches internally and returns _unscored() entries for just that chunk's jobs. These
# tests drive the real entry point (score_jobs_batch), mocking only claude_chat, so a
# regression in that internal try/except (e.g. someone "simplifying" it away) would be caught
# here exactly as it would in production.

def test_chunk_level_ai_failure_only_blanks_out_that_chunks_jobs(patch_ai_chat, monkeypatch):
    """Core regression test for the 2026-07-16 incident: 50 jobs -> 3 chunks (20, 20, 10). The
    middle chunk's ai_chat call fails outright; the other two chunks (recorded real responses)
    must still score normally, not get blanked out with it."""
    jobs = make_recorded_jobs(50)
    good0 = load_recorded("stage1_score", "batch_050_chunk0")
    good2 = load_recorded("stage1_score", "batch_050_chunk2")
    calls = {"n": 0}

    def flaky(prompt, system="", max_tokens=4096, quality=False):
        calls["n"] += 1
        if calls["n"] == 2:  # the middle chunk (jobs 20-39)
            raise RuntimeError("simulated transient failure")
        return good0 if calls["n"] == 1 else good2

    monkeypatch.setattr(stage1_scrape, "claude_chat", flaky)

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(results) == 50
    chunk0_urls = {j["url"] for j in jobs[0:20]}
    chunk1_urls = {j["url"] for j in jobs[20:40]}
    chunk2_urls = {j["url"] for j in jobs[40:50]}
    by_url = {r["url"]: r for r in results}

    assert all(by_url[u]["scored"] for u in chunk0_urls), "chunk 0 must score normally"
    assert all(by_url[u]["scored"] for u in chunk2_urls), "chunk 2 must score normally"
    assert all(not by_url[u]["scored"] for u in chunk1_urls), "only the failing chunk is blanked"
    assert all(by_url[u]["score"] is None for u in chunk1_urls), "never fabricate a score"


def test_chunk_level_malformed_response_only_blanks_out_that_chunks_jobs(monkeypatch):
    """Same isolation guarantee, but the failure mode is a malformed/unparseable response for
    one chunk (not an exception) — the other chunk's jobs must be unaffected either way."""
    jobs = make_recorded_jobs(21)  # 2 chunks: 20, 1
    good_response = load_recorded("stage1_score", "batch_021_chunk0")
    calls = {"n": 0}

    def flaky(prompt, system="", max_tokens=4096, quality=False):
        calls["n"] += 1
        if calls["n"] == 2:  # the second chunk (the 1-job tail) returns garbage
            return "I couldn't process that request."
        return good_response

    monkeypatch.setattr(stage1_scrape, "claude_chat", flaky)

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert len(results) == 21
    first_chunk_urls = {j["url"] for j in jobs[:20]}
    last_job_url = jobs[20]["url"]
    by_url = {r["url"]: r for r in results}
    assert all(by_url[u]["scored"] for u in first_chunk_urls)
    assert by_url[last_job_url]["scored"] is False
    assert by_url[last_job_url]["score"] is None


# ── Characterization test: unclamped ATS score (documented, not fixed) ─────

def test_unclamped_ats_score_is_a_known_gap_not_a_regression(patch_ai_chat):
    """Characterization test, not a bug fix: _score_jobs_chunk does int(entry["score"]) with
    no 0-100 clamp. A model reply outside that range (150, or negative) passes straight
    through unclamped — documented in docs/backlog/step-9-evals-testing.md's non-goals as a
    known gap. If this test starts failing, either the gap was fixed (update this test) or a
    clamp regressed silently (also worth knowing)."""
    jobs = make_recorded_jobs(1)
    canned = [{"url": jobs[0]["url"], "score": 150, "missing_keywords": [],
               "sponsorship": "unknown", "company_type": "product"}]
    patch_ai_chat(stage1_scrape, response=json.dumps(canned))

    results = stage1_scrape.score_jobs_batch(jobs, "resume text")

    assert results[0]["scored"] is True
    assert results[0]["score"] == 150  # not clamped to 100 — the documented gap
