"""
Stage 7 Notion/runner contract tests (scripts/autoapply.py run()).

Two invariants dominate this file, both drawn from how comparable auto-appliers fail in the
wild rather than from theory:

  1. The stage must never report an application it did not make. Tools that mark jobs
     "applied" on an unverified assumption corrupt the tracker in the direction you can't
     recover from — you stop re-applying to jobs you never actually applied to.
  2. A status write Notion silently ignored must not leave the job looking un-processed, or
     the next run picks it up again and re-does the work.
"""
from pathlib import Path

import pytest

from scripts import autoapply
from scripts.autoapply import run, STATUS_QUEUED, STATUS_NEEDS_Q, WRITABLE_STATUSES

ALL_STATUSES = WRITABLE_STATUSES | {"Resume Tailored"}


@pytest.fixture
def stage7(monkeypatch, tmp_path, patch_notion_db):
    """Patch the Notion layer and redirect answer sheets into tmp_path."""
    monkeypatch.setattr(autoapply, "APPLICATIONS_DIR", str(tmp_path))
    monkeypatch.setattr(autoapply, "ensure_dirs", lambda: None)
    monkeypatch.setattr(autoapply, "AUTOAPPLY_DAILY_CAP", 10)
    db = patch_notion_db(autoapply)
    db.known_statuses = ALL_STATUSES
    return db


def _seed(db, tmp_path, **over):
    resume = tmp_path / "resume.docx"
    resume.write_text("resume")
    fields = {
        "title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "url": "https://careers.acme.com/apply/1",   # 'unknown' channel → no network
        "ats_score": 80,
        "resume_link": resume.as_uri(),
    }
    fields.update(over)
    return db.seed(status="Resume Tailored", **fields)


# ── Invariant 1: never claims success ─────────────────────────────────────────

def test_applied_is_not_a_writable_status():
    assert "Applied" not in WRITABLE_STATUSES


def test_run_never_writes_applied(stage7, tmp_path, monkeypatch):
    """Behavioral counterpart to the constant check: whatever path a job takes through the
    stage, it must not come out claiming to have been applied to."""
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    _seed(stage7, tmp_path)
    _seed(stage7, tmp_path, company="Beta Inc")
    run()
    assert all(p["status"] != "Applied" for p in stage7._pages.values())


def test_source_has_no_submit_click():
    """Layer 2 must contain no submit code path at all — not behind a flag, not behind config.
    A grep-level assertion is crude but it is the one check that cannot be satisfied by a
    subtly-wrong implementation."""
    src = (Path(__file__).parent.parent / "scripts" / "autoapply_browser.py").read_text(
        encoding="utf-8").lower()
    for banned in ('click("submit', "click('submit", '.click()', "submit_button", "press(\"enter\")"):
        assert banned not in src, f"browser layer must not submit: found {banned!r}"


# ── Invariant 2: unverified status writes don't silently re-queue work ────────

def test_job_is_skipped_when_notion_drops_the_status(stage7, tmp_path, monkeypatch, capsys):
    """Reproduces the real footgun: the user hasn't hand-added 'Application Queued' to the
    Status select, so Notion accepts the write and ignores that property."""
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    stage7.known_statuses = {"Resume Tailored"}      # none of the stage-7 statuses exist
    page_id = _seed(stage7, tmp_path)

    run()

    assert stage7._pages[page_id]["status"] == "Resume Tailored"
    assert "skipped" in capsys.readouterr().out.lower()


def test_verified_write_moves_the_job_off_resume_tailored(stage7, tmp_path, monkeypatch):
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    page_id = _seed(stage7, tmp_path)
    run()
    assert stage7._pages[page_id]["status"] in WRITABLE_STATUSES


# ── Gating, attempts, and bookkeeping ─────────────────────────────────────────

def test_unresolved_eligibility_routes_to_needs_human(stage7, tmp_path, monkeypatch):
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": None, "requires_sponsorship": None})
    monkeypatch.setattr(autoapply, "GENERIC_QUESTIONS", {"questions": [
        {"label": "Are you legally authorized to work in the United States?",
         "required": True, "fields": [{"name": "q1", "type": "input_text"}]},
    ]})
    page_id = _seed(stage7, tmp_path)
    run()
    rec = stage7._pages[page_id]
    assert rec["status"] == STATUS_NEEDS_Q
    assert "authorized" in rec["needs_human_reason"].lower()


def test_apply_attempts_increments_from_prior_value(stage7, tmp_path, monkeypatch):
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    page_id = _seed(stage7, tmp_path, apply_attempts=2)
    run()
    assert stage7._pages[page_id]["apply_attempts"] == 3


def test_channel_is_recorded_for_triage(stage7, tmp_path, monkeypatch):
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    page_id = _seed(stage7, tmp_path, url="https://jobs.lever.co/acme/xyz")
    run()
    assert stage7._pages[page_id]["apply_channel"] == "lever"


def test_answer_sheet_is_written_even_when_the_job_needs_a_human(stage7, tmp_path, monkeypatch):
    """The sheet is the deliverable that makes a blocked job fast to finish by hand, so it must
    not be withheld precisely when the human is the one who has to act."""
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"work_authorized": None, "requires_sponsorship": None})
    _seed(stage7, tmp_path)
    run()
    assert list(tmp_path.glob("*.html"))


def test_daily_cap_limits_volume(stage7, tmp_path, monkeypatch):
    """High application velocity is itself scored against the candidate by modern ATSes, so the
    cap is a quality guard, not just politeness."""
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    monkeypatch.setattr(autoapply, "AUTOAPPLY_DAILY_CAP", 2)
    for i in range(5):
        _seed(stage7, tmp_path, company=f"Co{i}")
    run()
    moved = [p for p in stage7._pages.values() if p["status"] != "Resume Tailored"]
    assert len(moved) == 2


def test_no_tailored_jobs_is_a_clean_noop(stage7, capsys):
    run()
    assert "resume tailored" in capsys.readouterr().out.lower()


# ── LinkedIn/Indeed are never fillable ───────────────────────────────────────

def test_linkedin_and_indeed_are_not_fillable_channels():
    """Not a config choice — automated applying there violates ToS and is behaviorally
    detected. They must never appear in the set the browser layer is allowed to drive."""
    assert "linkedin" not in autoapply.FILLABLE_CHANNELS
    assert "indeed" not in autoapply.FILLABLE_CHANNELS


def test_fill_is_refused_for_a_manual_only_channel(stage7, tmp_path, monkeypatch):
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})

    called = []
    monkeypatch.setattr(autoapply, "_fill_one", lambda *a, **k: called.append(a))
    _seed(stage7, tmp_path, url="https://www.linkedin.com/jobs/view/999")
    run(fill=True)
    assert called == []
