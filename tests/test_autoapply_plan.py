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


# ── Structured address block ──────────────────────────────────────────────────

@pytest.mark.parametrize("label,pkey,value", [
    ("Legal First Name", "legal_first_name", "Krishna"),
    ("Legal Last Name", "legal_last_name", "Achyuth"),
    ("Address Line 1", "address_line1", "123 Main St"),
    ("Address Line 2", "address_line2", "Apt 4B"),
    ("City", "city", "Austin"),
    ("State", "state", "TX"),
    ("Country", "country", "United States"),
    ("Zip Code", "zip_code", "78701"),
    ("Address Type", "address_type", "Home"),
])
def test_address_labels_resolve_from_the_address_profile(label, pkey, value):
    profile = {pkey: value}
    plan = build_application_plan(_labelled(label, required=True), profile=profile)
    field = plan["fields"][0]
    assert field["status"] == "ready"
    assert field["value"] == value
    assert f"profile.{pkey}" in field["source"]


def test_blank_address_field_is_review_required():
    plan = build_application_plan(_labelled("City"), profile={"city": ""})
    assert plan["fields"][0]["status"] == "review_required"


def test_legal_first_name_does_not_fall_back_to_first_name():
    """Legal name (ID) and the resume/outreach display name are independent facts — a wizard
    answer for one must never silently satisfy the other."""
    profile = {"first_name": "Kach", "legal_first_name": ""}
    plan = build_application_plan(_labelled("Legal First Name"), profile=profile)
    assert plan["fields"][0]["status"] == "review_required"


# ── Attachment dual-row dedupe ─────────────────────────────────────────────────

def _dual_attachment_schema(label="Resume/CV", required=True, order=("input_file", "textarea")):
    fields = []
    for ftype in order:
        name = "resume" if ftype == "input_file" else "resume_text"
        fields.append({"name": name, "type": ftype})
    return {"questions": [{"label": label, "required": required, "fields": fields}]}


def test_attachment_textarea_sibling_mirrors_the_upload_status(tmp_path):
    resume = tmp_path / "r.docx"
    resume.write_text("resume")
    plan = build_application_plan(_dual_attachment_schema(), resume_path=str(resume))
    assert len(plan["fields"]) == 2
    upload, textarea = plan["fields"][0], plan["fields"][1]
    assert upload["status"] == "ready"
    assert textarea["status"] == "ready"
    assert textarea["value"] == upload["value"]
    assert "dedup" in textarea["source"]


def test_attachment_textarea_sibling_blocks_when_resume_is_missing(tmp_path):
    """The dedup must mirror the real state, not always say ready — a missing resume must
    still block via either row."""
    plan = build_application_plan(_dual_attachment_schema(), resume_path="")
    assert all(f["status"] == "review_required" for f in plan["fields"])


def test_attachment_order_independence(tmp_path):
    """Dedup must not depend on input_file being listed before the textarea."""
    resume = tmp_path / "r.docx"
    resume.write_text("resume")
    schema = _dual_attachment_schema(label="Cover Letter", order=("textarea", "input_file"))
    plan = build_application_plan(schema, resume_path=str(resume))
    assert all(f["status"] == "ready" for f in plan["fields"])


def test_dedup_fix_removes_a_spurious_blocker(tmp_path):
    """Direct regression for the TODO's reported symptom: a satisfied resume upload must not
    still count as a blocking required field via its textarea sibling."""
    resume = tmp_path / "r.docx"
    resume.write_text("resume")
    plan = build_application_plan(_dual_attachment_schema(), resume_path=str(resume))
    rpt = readiness_report(plan)
    assert rpt["counts"]["blocking"] == 0


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


def test_resolve_tailored_resume_downloads_ci_hosted_url(monkeypatch, tmp_path):
    """A CI-tailored job's link is a raw.githubusercontent.com URL, not file:// — resolve it by
    downloading the bytes into RESUMES_DIR rather than treating it as a local path."""
    monkeypatch.setattr(autoapply, "RESUMES_DIR", str(tmp_path))

    class FakeResponse:
        status_code = 200
        content = b"fake docx bytes"

    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResponse())

    url = "https://raw.githubusercontent.com/o/r/tailored-resumes/output/resumes/x.docx"
    result = resolve_tailored_resume({"resume_link": url})

    assert result == str(tmp_path / "x.docx")
    assert (tmp_path / "x.docx").read_bytes() == b"fake docx bytes"


def test_resolve_tailored_resume_download_failure_returns_blank(monkeypatch, tmp_path):
    monkeypatch.setattr(autoapply, "RESUMES_DIR", str(tmp_path))

    class FakeResponse:
        status_code = 404
        content = b""

    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResponse())

    url = "https://raw.githubusercontent.com/o/r/tailored-resumes/output/resumes/gone.docx"
    assert resolve_tailored_resume({"resume_link": url}) == ""


def test_resolve_tailored_resume_download_network_error_returns_blank(monkeypatch, tmp_path):
    import requests

    monkeypatch.setattr(autoapply, "RESUMES_DIR", str(tmp_path))

    def raise_error(url, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr("requests.get", raise_error)

    url = "https://raw.githubusercontent.com/o/r/tailored-resumes/output/resumes/x.docx"
    assert resolve_tailored_resume({"resume_link": url}) == ""


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
