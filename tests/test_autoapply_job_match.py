"""
Stage 7 Layer 3 bridge — /plan + identify_job() + /resume/meta (step-15b).

Pure-function tests (identify_job, _dom_to_schema, build_plan_response,
build_resume_meta_response) driven directly, not over HTTP — the wire-level cases for /plan and
/resume/meta live in tests/test_autoapply_server.py alongside the rest of the HTTP contract.
"""
from pathlib import Path

import pytest

from scripts import autoapply, autoapply_server as srv
from scripts.autoapply import SAMPLE_QUESTIONS, build_application_plan, WRITABLE_STATUSES

_FULL_PROFILE = {
    "first_name": "Ada", "last_name": "Lovelace", "full_name": "Ada Lovelace",
    "email": "ada@example.com", "phone": "555-0100", "location": "",
    "linkedin_url": "", "github_url": "", "portfolio_url": "",
    "work_authorized": True, "requires_sponsorship": False,
}


@pytest.fixture(autouse=True)
def _deterministic_profile(monkeypatch):
    """Every /plan test in this file must not depend on this machine's local
    config/application_profile.json overlay (e.g. an un-configured YOUR_NAME placeholder
    derives to blank first/last names) — pin a known-complete profile instead."""
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE", dict(_FULL_PROFILE))
    monkeypatch.setattr(autoapply, "APPLICATION_ADDRESS", {})


# ── identify_job() ──────────────────────────────────────────────────────────

def _job(page_id, url, title="A Job", company="Acme", **over):
    return {"page_id": page_id, "title": title, "company": company, "url": url,
            "resume_link": "", **over}


def test_rung0_known_page_id_short_circuits_before_any_url_matching():
    pool = [_job("p1", "https://boards.greenhouse.io/acme/jobs/1"),
            _job("p2", "https://boards.greenhouse.io/acme/jobs/2")]
    # A live URL that would otherwise ambiguously match nothing/rung3 — page_id must win outright.
    result = srv.identify_job(pool, "https://totally-unrelated.example.com/apply", page_id="p2")
    assert result["status"] == "known"
    assert result["rung"] == 0
    assert result["page_id"] == "p2"
    assert result["job"]["page_id"] == "p2"
    assert result["candidates"] == []


def test_rung1_exact_url_match():
    url = "https://boards.greenhouse.io/acme/jobs/123"
    pool = [_job("p1", url)]
    result = srv.identify_job(pool, url)
    assert result == {"status": "matched", "page_id": "p1", "job": pool[0], "rung": 1,
                       "confidence": "exact", "candidates": []}


def test_rung1_normalized_query_stripped():
    pool = [_job("p1", "https://boards.greenhouse.io/acme/jobs/123")]
    result = srv.identify_job(pool, "https://boards.greenhouse.io/acme/jobs/123?gh_src=xyz")
    assert result["status"] == "matched" and result["rung"] == 1
    assert result["confidence"] == "normalized"


def test_rung1_normalized_trailing_apply_stripped():
    pool = [_job("p1", "https://boards.greenhouse.io/acme/jobs/123")]
    result = srv.identify_job(pool, "https://boards.greenhouse.io/acme/jobs/123/apply")
    assert result["status"] == "matched" and result["page_id"] == "p1"


def test_rung1_normalized_job_boards_host_folded():
    pool = [_job("p1", "https://boards.greenhouse.io/acme/jobs/123")]
    result = srv.identify_job(pool, "https://job-boards.greenhouse.io/acme/jobs/123")
    assert result["status"] == "matched" and result["page_id"] == "p1"


def test_rung2_greenhouse_gh_jid_aggregator_link():
    pool = [_job("p1", "https://boards.greenhouse.io/acme/jobs/999")]
    # An aggregator link carrying the job id via query, on a totally different host/path shape.
    live_url = "https://boards.greenhouse.io/embed/job_app?token=999&for=acme"
    result = srv.identify_job(pool, live_url)
    assert result["status"] == "matched"
    assert result["rung"] == 2
    assert result["page_id"] == "p1"
    assert result["confidence"] == "greenhouse_ids"


def test_two_matches_is_ambiguous_and_picks_neither():
    url = "https://boards.greenhouse.io/acme/jobs/123"
    pool = [_job("p1", url), _job("p2", url, company="Acme Duplicate Posting")]
    result = srv.identify_job(pool, url)
    assert result["status"] == "ambiguous"
    assert result["page_id"] is None
    assert result["job"] is None
    assert len(result["candidates"]) == 2


def test_no_match_falls_through_to_ask_with_full_pool():
    pool = [_job("p1", "https://boards.greenhouse.io/acme/jobs/1"),
            _job("p2", "https://boards.lever.co/other/2")]
    result = srv.identify_job(pool, "https://careers.somecompany.com/apply/42")
    assert result["status"] == "ask"
    assert result["page_id"] is None
    assert result["job"] is None
    assert result["candidates"] == pool


def test_candidate_pool_status_set_includes_application_queued():
    """A naive 'Resume Tailored'-only pool would miss a job Stage 7 already planned."""
    assert "Application Queued" in srv.CANDIDATE_STATUSES
    assert "Resume Tailored" in srv.CANDIDATE_STATUSES
    assert srv.CANDIDATE_STATUSES == sorted(WRITABLE_STATUSES | {"Resume Tailored"})


# ── _dom_to_schema() ─────────────────────────────────────────────────────────

def _sample_questions_as_dom() -> dict:
    """Re-express autoapply.SAMPLE_QUESTIONS in the raw DOM-scrape shape a content script would
    realistically send (domType/options instead of the internal type/values vocabulary)."""
    reverse_type = {
        "input_text": "text", "input_file": "file", "textarea": "textarea",
        "multi_value_single_select": "select",
    }
    questions = []
    for q in SAMPLE_QUESTIONS["questions"]:
        fields = []
        for f in q["fields"]:
            dom_field = {"name": f["name"], "domType": reverse_type[f["type"]]}
            if "values" in f:
                dom_field["options"] = f["values"]
            fields.append(dom_field)
        questions.append({"label": q["label"], "required": q["required"], "fields": fields})
    return {"title": SAMPLE_QUESTIONS["title"], "questions": questions}


def test_dom_to_schema_yields_field_for_field_identical_plan():
    """The proof this bridge adds no answer logic of its own: a DOM payload equivalent to
    SAMPLE_QUESTIONS must plan identically to SAMPLE_QUESTIONS itself."""
    dom_payload = _sample_questions_as_dom()
    schema = srv._dom_to_schema(dom_payload)

    plan_from_dom = build_application_plan(schema, resume_path="/tmp/resume.docx")
    plan_from_sample = build_application_plan(SAMPLE_QUESTIONS, resume_path="/tmp/resume.docx")

    assert plan_from_dom["fields"] == plan_from_sample["fields"]


def test_dom_to_schema_unknown_dom_type_degrades_to_input_text():
    dom = {"title": "t", "questions": [
        {"label": "Mystery Field", "required": False,
         "fields": [{"name": "mystery", "domType": "some-future-html5-input"}]},
    ]}
    schema = srv._dom_to_schema(dom)
    assert schema["questions"][0]["fields"][0]["type"] == "input_text"


# ── build_plan_response() ────────────────────────────────────────────────────

@pytest.fixture
def bridge_db(monkeypatch, patch_notion_db):
    monkeypatch.setattr(srv, "_candidate_pool_cache", None)
    return patch_notion_db(srv)


def _dom_payload():
    return _sample_questions_as_dom()


def test_plan_writes_no_status_read_only(bridge_db, tmp_path):
    resume = tmp_path / "resume.docx"
    resume.write_text("resume")
    page_id = bridge_db.seed(status="Resume Tailored",
                              title="Backend Engineer", company="Acme",
                              url="https://boards.greenhouse.io/acme/jobs/1",
                              resume_link=resume.as_uri())
    resp = srv.build_plan_response({
        "live_url": "https://boards.greenhouse.io/acme/jobs/1", "dom": _dom_payload(),
    })
    assert resp["job_match"]["status"] == "matched"
    assert resp["job_match"]["page_id"] == page_id
    assert bridge_db._pages[page_id]["status"] == "Resume Tailored"  # untouched


def test_plan_no_match_resume_review_required_rest_still_resolves(bridge_db):
    bridge_db.seed(status="Resume Tailored", url="https://boards.greenhouse.io/acme/jobs/1")
    resp = srv.build_plan_response({
        "live_url": "https://careers.example.com/apply/999", "dom": _dom_payload(),
    })
    assert resp["job_match"]["status"] == "ask"
    resume_field = next(f for f in resp["plan"]["fields"] if f["type"] == "input_file")
    assert resume_field["status"] == "review_required"
    assert resume_field["source"] == "resume-missing"
    # Everything else still resolves from the static profile, independent of job match.
    name_field = next(f for f in resp["plan"]["fields"] if f["name"] == "first_name")
    assert name_field["status"] == "ready"


def test_plan_readonly_channel_overrides_every_field(bridge_db):
    resp = srv.build_plan_response({
        "live_url": "https://www.linkedin.com/jobs/view/12345", "dom": _dom_payload(),
    })
    assert resp["channel"] == "linkedin"
    assert all(f["status"] == "review_required" for f in resp["plan"]["fields"])
    assert all(f["value"] is None for f in resp["plan"]["fields"])
    assert all(f["source"] == srv._READONLY_SOURCE for f in resp["plan"]["fields"])


def test_plan_known_page_id_skips_candidate_pool_matching(bridge_db, tmp_path, monkeypatch):
    resume = tmp_path / "resume.docx"
    resume.write_text("resume")
    page_id = bridge_db.seed(status="Resume Tailored", title="Job A", company="Acme",
                              url="https://boards.greenhouse.io/acme/jobs/1",
                              resume_link=resume.as_uri())
    calls = {"n": 0}
    real_identify = srv.identify_job

    def spy(pool, live_url, page_id=None):
        calls["n"] += 1
        return real_identify(pool, live_url, page_id=page_id)

    monkeypatch.setattr(srv, "identify_job", spy)
    resp = srv.build_plan_response({
        "live_url": "https://totally-unrelated.example.com/apply",
        "page_id": page_id, "dom": _dom_payload(),
    })
    assert resp["job_match"]["status"] == "known"
    assert resp["job_match"]["page_id"] == page_id
    assert calls["n"] == 1  # identify_job is called once; internally it short-circuits at rung 0


# ── build_resume_meta_response() ─────────────────────────────────────────────

def test_resume_meta_returns_filename_size_mime_no_bytes(bridge_db, tmp_path):
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"fake docx bytes")
    page_id = bridge_db.seed(status="Resume Tailored", url="https://x.com/1",
                              resume_link=resume.as_uri())
    result = srv.build_resume_meta_response(page_id)
    assert result["filename"] == "tailored.docx"
    assert result["size"] == len(b"fake docx bytes")
    assert result["mime"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert Path(result["abs_path"]) == resume
    assert "bytes" not in result and "content" not in result


def test_resume_meta_unknown_page_id_errors(bridge_db):
    result = srv.build_resume_meta_response("no-such-page")
    assert "error" in result


def test_resume_meta_works_on_readonly_channel_job(bridge_db, tmp_path):
    """Path display isn't 'filling' — /resume/meta must still work for a LinkedIn-sourced job."""
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"x")
    page_id = bridge_db.seed(status="Resume Tailored",
                              url="https://www.linkedin.com/jobs/view/1",
                              resume_link=resume.as_uri())
    result = srv.build_resume_meta_response(page_id)
    assert result["filename"] == "tailored.docx"
