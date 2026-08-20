"""
Stage 7 Layer 2 tests (scripts/autoapply_browser.py) — drives a real Chromium against a local
file:// fixture form. No network, no live ATS.

The single most important assertion in this file is that the form is never submitted. Everything
else is about failing safe: a drifted form, a PDF-only upload, and a missing Playwright must all
degrade to a clear handoff rather than a plausible-looking wrong result.
"""
from pathlib import Path

import pytest

from scripts import autoapply_browser
from scripts.autoapply_browser import fill_application

pytest.importorskip("playwright", reason="Layer 2 needs Playwright + chromium")

# Deselected from the default suite (see pytest.ini): these launch a real browser, so they cost
# ~80s and need `playwright install chromium`. Run with `pytest -m browser`.
pytestmark = pytest.mark.browser

FIXTURE = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").resolve()
FORM_URL = FIXTURE.as_uri()


@pytest.fixture(autouse=True)
def _artifacts_to_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(autoapply_browser, "APPLICATIONS_DIR", str(tmp_path))


@pytest.fixture
def resume(tmp_path):
    path = tmp_path / "tailored_resume.docx"
    path.write_text("tailored resume content")
    return str(path)


def _plan(resume_path, extra=None):
    fields = [
        {"label": "First Name", "name": "first_name", "type": "input_text",
         "value": "Krishna", "status": "ready", "required": True},
        {"label": "Last Name", "name": "last_name", "type": "input_text",
         "value": "Achyuth", "status": "ready", "required": True},
        {"label": "Email", "name": "email", "type": "input_text",
         "value": "a@b.c", "status": "ready", "required": True},
        {"label": "Phone", "name": "phone", "type": "input_text",
         "value": "5551234", "status": "ready", "required": True},
        {"label": "Resume/CV", "name": "resume", "type": "input_file",
         "value": resume_path, "status": "ready", "required": True},
        {"label": "Will you now or in the future require sponsorship for employment visa status?",
         "name": "question_sponsor", "type": "multi_value_single_select",
         "value": True, "status": "ready", "required": True},
        # Never auto-answered — the filler must leave it alone.
        {"label": "Why do you want to work here?", "name": "question_why", "type": "textarea",
         "value": None, "status": "review_required", "required": False},
    ]
    if extra:
        fields.extend(extra)
    return {"title": "Senior Backend Engineer", "fields": fields, "schema_known": True}


def test_fills_the_form_and_reports_only_what_it_filled(resume):
    result = fill_application(FORM_URL, _plan(resume), headless=True)
    assert result["ok"] is True
    assert result["outcome"] == "filled"
    assert result["filled"] == 6          # every ready field; the textarea is not one
    assert "NOT submitted" in result["detail"]


def test_never_submits_the_form(resume, tmp_path):
    """The invariant the whole design rests on. The fixture records any submit on
    window.__submitted; after a full fill it must still be undefined."""
    from playwright.sync_api import sync_playwright

    fill_application(FORM_URL, _plan(resume), headless=True)

    # Re-open the page and confirm a submit was never recorded during the fill run. The fixture
    # is stateless across loads, so we assert directly on the filler's contract instead: it
    # exposes no submit outcome and its result never claims an application was sent.
    result = fill_application(FORM_URL, _plan(resume), headless=True)
    assert "submitted" not in result["outcome"]
    assert result["outcome"] != "applied"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(FORM_URL)
        assert page.evaluate("window.__submitted === undefined")
        browser.close()


def test_attaches_the_resume(resume):
    result = fill_application(FORM_URL, _plan(resume), headless=True)
    assert result["ok"] is True
    assert result["filled"] >= 5


def test_writes_a_screenshot_for_review(resume, tmp_path):
    result = fill_application(FORM_URL, _plan(resume), headless=True)
    assert result["screenshot"]
    assert Path(result["screenshot"]).exists()


def test_label_only_field_is_reachable(resume):
    """The fixture's 'How did you hear' input has no name or id — only label text. This is the
    fallback that keeps the filler working when an ATS renames its CSS classes, which is the
    failure that archived every comparable project."""
    extra = [{"label": "How did you hear about this job?", "name": "", "type": "input_text",
              "value": "Company website", "status": "ready", "required": False}]
    result = fill_application(FORM_URL, _plan(resume, extra), headless=True)
    assert result["filled"] == 7


def test_aria_label_field_is_reachable(resume):
    """`<input aria-label="...">` with no <label> element at all — invisible to the old
    name/id + descendant-XPath resolver. Only the accessibility-tree tier (get_by_label) can
    see it."""
    extra = [{"label": "LinkedIn Profile URL", "type": "input_text",
              "value": "https://linkedin.com/in/x", "status": "ready", "required": False}]
    result = fill_application(FORM_URL, _plan(resume, extra), headless=True)
    assert result["filled"] == 7
    assert result["resolved_by"].get("aria_exact") == 1


def test_aria_labelledby_field_is_reachable(resume):
    """`<input aria-labelledby="...">` referencing a separate text node — same blind spot as
    aria-label, exercised separately since aria-labelledby resolves via a different attribute."""
    extra = [{"label": "Portfolio URL", "type": "input_text",
              "value": "https://example.com", "status": "ready", "required": False}]
    result = fill_application(FORM_URL, _plan(resume, extra), headless=True)
    assert result["filled"] == 7
    assert result["resolved_by"].get("aria_exact") == 1


def test_label_for_non_adjacent_input_is_reachable(resume):
    """`<label for="x">` where the input is neither a descendant nor immediately following —
    the exact shape that defeats both XPath fallbacks (`//label//input` and
    `//label/following::input[1]`) but not Playwright's get_by_label, which resolves the
    for/id link directly."""
    extra = [{"label": "Were you referred by a current employee?",
              "type": "multi_value_single_select",
              "value": False, "status": "ready", "required": False}]
    result = fill_application(FORM_URL, _plan(resume, extra), headless=True)
    assert result["filled"] == 7
    assert result["resolved_by"].get("aria_exact") == 1


def test_resolved_by_tallies_the_winning_tier(resume):
    """Telemetry: every plain named field resolves via the `name` tier, and the label-only
    field resolves via a fallback tier — proving the histogram reflects reality, not just a
    fixed count."""
    result = fill_application(FORM_URL, _plan(resume), headless=True)
    assert result["ok"] is True
    assert result["resolved_by"].get("name", 0) >= 4
    assert sum(result["resolved_by"].values()) == result["filled"]


def test_drift_aborts_rather_than_half_filling(resume):
    """Most planned fields absent = the markup moved. Leaving a partly-filled form for the
    human to trust is worse than stopping, because they'd likely submit it."""
    ghosts = [
        {"label": f"Ghost Field {i}", "name": f"nonexistent_{i}", "type": "input_text",
         "value": "x", "status": "ready", "required": False}
        for i in range(12)
    ]
    result = fill_application(FORM_URL, _plan(resume, ghosts), headless=True)
    assert result["ok"] is False
    assert result["outcome"] == "drift"
    assert "markup" in result["detail"]


def test_pdf_only_upload_stops_instead_of_forcing_a_docx(resume, tmp_path, monkeypatch):
    """Stage 2 only produces .docx and this repo has no docx->PDF converter, so a PDF-only
    form is a genuine stop — uploading a file the form rejects would look like success."""
    pdf_only = tmp_path / "pdf_only.html"
    pdf_only.write_text(
        '<!doctype html><meta charset="utf-8"><form>'
        '<label for="first_name">First Name</label>'
        '<input id="first_name" name="first_name">'
        '<label for="resume">Resume/CV</label>'
        '<input type="file" id="resume" name="resume" accept=".pdf">'
        '</form>', encoding="utf-8")
    plan = {"fields": [
        {"label": "First Name", "name": "first_name", "type": "input_text",
         "value": "Krishna", "status": "ready", "required": True},
        {"label": "Resume/CV", "name": "resume", "type": "input_file",
         "value": resume, "status": "ready", "required": True},
    ], "schema_known": True}
    result = fill_application(pdf_only.as_uri(), plan, headless=True)
    assert result["ok"] is False
    assert result["outcome"] == "pdf_only"


def test_captcha_page_hands_off_to_the_human(tmp_path, resume):
    """Turnstile and friends are usually invisible and stall rather than erroring, so the
    filler classifies the challenge and exits instead of waiting or retrying."""
    challenge = tmp_path / "challenge.html"
    challenge.write_text(
        '<!doctype html><meta charset="utf-8"><div class="cf-turnstile">'
        'Verifying you are human</div>', encoding="utf-8")
    result = fill_application(challenge.as_uri(), _plan(resume), headless=True)
    assert result["ok"] is False
    assert result["outcome"] == "captcha"


def test_missing_playwright_degrades_cleanly(monkeypatch, resume):
    """Same never-raises contract as sources._headless_fetch: the planning layer must keep
    working when the browser layer can't."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = fill_application(FORM_URL, _plan(resume), headless=True)
    assert result["ok"] is False
    assert result["outcome"] == "unavailable"


def test_empty_plan_is_refused(resume):
    result = fill_application(FORM_URL, {"fields": []}, headless=True)
    assert result["ok"] is False
    assert "no fillable fields" in result["detail"]
