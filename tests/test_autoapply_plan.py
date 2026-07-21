"""
Stage 7 planning-layer contract tests (scripts/autoapply.py).

This is the layer that decides what answer goes in every box, and it is the half that must
never be wrong: a bad eligibility answer is submitted under the user's name and cannot be
retracted. These tests pin that behavior rather than the incidental formatting around it.
"""
import pytest

from scripts import autoapply
from scripts.autoapply import (
    detect_apply_channel, parse_greenhouse_url, build_application_plan,
    readiness_report, resolve_tailored_resume, SAMPLE_QUESTIONS,
    STATUS_QUEUED, STATUS_NEEDS_Q,
)


# ── Channel routing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse"),
    ("https://job-boards.greenhouse.io/acme/jobs/123", "greenhouse"),
    ("https://jobs.lever.co/acme/abc-def", "lever"),
    ("https://jobs.ashbyhq.com/acme/xyz", "ashby"),
    ("https://acme.wd1.myworkdayjobs.com/en-US/careers/job/x", "workday"),
    ("https://www.linkedin.com/jobs/view/12345", "linkedin"),
    ("https://www.indeed.com/viewjob?jk=abc", "indeed"),
    ("https://careers.acme.com/apply/42", "unknown"),
    ("", "unknown"),
])
def test_detect_apply_channel(url, expected):
    assert detect_apply_channel(url) == expected


@pytest.mark.parametrize("url", [
    "https://evilgreenhouse.io/acme/jobs/1",
    "https://notlever.co/acme/x",
    "https://greenhouse.io.attacker.test/acme/jobs/1",
])
def test_lookalike_domains_do_not_route_to_a_trusted_channel(url):
    """A bare endswith() check would route all of these to a trusted channel — and a trusted
    channel is one the browser layer is allowed to fill and upload a resume into. The match
    must be on a real domain boundary."""
    assert detect_apply_channel(url) == "unknown"


# ── Greenhouse URL shapes ─────────────────────────────────────────────────────

@pytest.mark.parametrize("url,token,job_id", [
    ("https://boards.greenhouse.io/acme/jobs/4012345", "acme", "4012345"),
    ("https://job-boards.greenhouse.io/acme/jobs/4012345", "acme", "4012345"),
    ("https://boards.greenhouse.io/embed/job_app?token=4012345&for=acme", "acme", "4012345"),
    ("https://boards.greenhouse.io/acme?gh_jid=4012345", "acme", "4012345"),
])
def test_parse_greenhouse_url_shapes(url, token, job_id):
    assert parse_greenhouse_url(url) == (token, job_id)


def test_parse_greenhouse_url_gives_up_cleanly():
    assert parse_greenhouse_url("https://boards.greenhouse.io/") == (None, None)


# ── Eligibility is never guessed ──────────────────────────────────────────────

def _labelled(label, ftype="input_text", required=True, name="q1"):
    return {"questions": [{"label": label, "required": required,
                           "fields": [{"name": name, "type": ftype}]}]}


@pytest.mark.parametrize("label", [
    "Are you legally authorized to work in the United States?",
    "Will you now or in the future require sponsorship for employment visa status?",
])
def test_unset_eligibility_always_needs_a_human(label):
    """The safety-critical case: with the fact unset, the answer must be withheld — not
    defaulted to yes, no, or whatever the form's first option happens to be."""
    profile = {"work_authorized": None, "requires_sponsorship": None}
    plan = build_application_plan(_labelled(label), profile=profile)
    field = plan["fields"][0]
    assert field["status"] == "review_required"
    assert field["value"] is None
    assert readiness_report(plan)["notion_status"] == STATUS_NEEDS_Q


def test_set_eligibility_is_answered_from_the_profile():
    profile = {"work_authorized": True, "requires_sponsorship": True}
    plan = build_application_plan(
        _labelled("Will you now or in the future require sponsorship?"), profile=profile)
    field = plan["fields"][0]
    assert field["status"] == "ready"
    assert field["value"] is True
    assert "profile.requires_sponsorship" in field["source"]


def test_eligibility_false_is_answered_not_treated_as_missing():
    """False is a real answer; only None means 'unknown'. A truthiness check here would
    silently escalate every no-sponsorship-needed candidate to human review."""
    profile = {"work_authorized": True, "requires_sponsorship": False}
    plan = build_application_plan(
        _labelled("Do you require visa sponsorship?"), profile=profile)
    assert plan["fields"][0]["status"] == "ready"
    assert plan["fields"][0]["value"] is False


# ── Preset banks ──────────────────────────────────────────────────────────────

def test_eeo_fields_use_the_preset_not_a_guess(monkeypatch):
    monkeypatch.setattr(autoapply, "EEO_RESPONSES", {"gender": "Decline To Self Identify"})
    plan = build_application_plan(_labelled("Gender", required=False))
    field = plan["fields"][0]
    assert field["status"] == "ready"
    assert field["value"] == "Decline To Self Identify"
    assert field["source"] == "EEO_RESPONSES"


def test_common_screener_uses_the_answer_bank(monkeypatch):
    monkeypatch.setattr(autoapply, "COMMON_QUESTION_PRESETS",
                        {"how did you hear": "Company website"})
    plan = build_application_plan(_labelled("How did you hear about this job?", required=False))
    assert plan["fields"][0]["value"] == "Company website"


def test_blank_preset_routes_to_human_rather_than_answering_empty(monkeypatch):
    """A preset the user left blank means 'I haven't decided', which must become a human
    prompt — not an empty string typed into a real application."""
    monkeypatch.setattr(autoapply, "COMMON_QUESTION_PRESETS", {"salary expectation": ""})
    plan = build_application_plan(_labelled("Salary expectation", required=True))
    assert plan["fields"][0]["status"] == "review_required"


def test_free_text_is_never_auto_answered():
    plan = build_application_plan(
        _labelled("Why do you want to work here?", ftype="textarea", required=False))
    field = plan["fields"][0]
    assert field["status"] == "review_required"
    assert field["value"] is None


def test_unmapped_field_is_never_guessed():
    plan = build_application_plan(_labelled("What is your favourite monorepo tool?"))
    assert plan["fields"][0]["status"] == "review_required"
    assert plan["fields"][0]["source"] == "unmapped"


# ── Readiness verdict ─────────────────────────────────────────────────────────

def test_blocking_required_field_forces_needs_human():
    plan = build_application_plan(SAMPLE_QUESTIONS,
                                  profile={"work_authorized": None}, resume_path="")
    rpt = readiness_report(plan)
    assert rpt["counts"]["blocking"] > 0
    assert rpt["notion_status"] == STATUS_NEEDS_Q


def test_unresolved_optional_fields_do_not_block(tmp_path):
    resume = tmp_path / "r.docx"
    resume.write_text("x")
    profile = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": "555",
               "work_authorized": True, "requires_sponsorship": True}
    plan = build_application_plan(SAMPLE_QUESTIONS, profile=profile, resume_path=str(resume))
    rpt = readiness_report(plan)
    assert rpt["counts"]["blocking"] == 0
    assert rpt["notion_status"] == STATUS_QUEUED


def test_unknown_schema_verdict_is_hedged():
    """With no public schema we cannot know what else the form asks, so the verdict must not
    claim completeness — the user needs to know to expect surprises."""
    plan = build_application_plan(SAMPLE_QUESTIONS, schema_known=False,
                                  profile={"work_authorized": True, "requires_sponsorship": True,
                                           "first_name": "A", "last_name": "B",
                                           "email": "a@b.c", "phone": "5"},
                                  resume_path="/tmp/r.docx")
    assert "PARTIAL" in readiness_report(plan)["verdict"]


# ── Resume round-trip ─────────────────────────────────────────────────────────

def test_resolve_tailored_resume_round_trips_a_file_url(tmp_path):
    resume = tmp_path / "2026-07-19_Acme_Engineer.docx"
    resume.write_text("resume")
    job = {"resume_link": resume.as_uri()}
    assert resolve_tailored_resume(job) == str(resume)


def test_resolve_tailored_resume_handles_spaces_in_the_path(tmp_path):
    resume = tmp_path / "Acme Corp Engineer.docx"
    resume.write_text("resume")
    assert resolve_tailored_resume({"resume_link": resume.as_uri()}) == str(resume)


def test_resolve_tailored_resume_returns_blank_when_file_is_gone(tmp_path):
    """Stage 2 may have run weeks ago and the file since been cleaned up. Returning a
    non-existent path would make the browser layer attach nothing while reporting success."""
    missing = tmp_path / "gone.docx"
    assert resolve_tailored_resume({"resume_link": missing.as_uri()}) == ""


def test_resolve_tailored_resume_handles_no_link():
    assert resolve_tailored_resume({}) == ""


def test_missing_resume_makes_the_upload_field_block():
    plan = build_application_plan(SAMPLE_QUESTIONS, resume_path="")
    upload = [f for f in plan["fields"] if f["type"] == "input_file"][0]
    assert upload["status"] == "review_required"


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_json_mode_emits_only_json(capsys):
    """--json has to be pipeable; a stray progress line on stdout makes it unparseable."""
    import json as _json
    autoapply.main(["--sample", "--json"])
    parsed = _json.loads(capsys.readouterr().out)
    assert parsed["plan"]["fields"]
    assert "verdict" in parsed["report"]
