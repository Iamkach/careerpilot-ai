"""
Tests for PR #11 review item #6: a zero-edit tailoring run must not be marked
"Resume Tailored" in Notion. save_resume([], job, resume_text) just produces a renamed,
unmodified copy of the base resume — advancing the status implies success that wasn't
achieved (the same "don't claim success you didn't achieve" principle stage 7's Never
Applied rule enforces). run()'s Phase 3 loop instead mirrors _sponsorship_gate()'s pattern:
park the job in "Human Review" with a guidance note, still saving/linking the resume file
for a human to inspect, rather than silently advancing or leaving it stuck in "Reviewed"
forever.
"""
from scripts import stage2_tailor


def _seed_reviewed(fake_db, company, slug, ats_score=70):
    return fake_db.seed(
        status="Reviewed",
        title="Backend Engineer",
        company=company,
        url=f"https://example.com/jobs/{slug}",
        description="Some cached job description text.",
        ats_score=ats_score,
    )


def _patch_common(monkeypatch, batch_results):
    monkeypatch.setattr(stage2_tailor, "load_base_resume_text", lambda: "resume text")
    monkeypatch.setattr(
        stage2_tailor, "tailor_resumes_batch",
        lambda resume_text, jobs_and_jds: batch_results,
    )
    monkeypatch.setattr(
        stage2_tailor, "save_resume",
        lambda edits, job, resume_text: "output/resumes/fake.docx",
    )
    monkeypatch.setattr(stage2_tailor, "extract_docx_text", lambda path: "tailored resume text")
    monkeypatch.setattr(
        stage2_tailor, "verify_tailored_score",
        lambda tailored_text, jd, job: {"url": job["url"], "score": 90, "scored": True},
    )


def test_nonempty_edits_still_marks_resume_tailored(monkeypatch, patch_notion_db):
    fake_db = patch_notion_db(stage2_tailor)
    pid = _seed_reviewed(fake_db, "Acme Corp", "acme")
    _patch_common(monkeypatch, {
        pid: ([{"old": "x", "new": "y", "reason": "r"}], ["kw1"]),
    })

    stage2_tailor.run(min_score=0)

    rec = fake_db._pages[pid]
    assert rec["status"] == "Resume Tailored"
    assert rec["tailored_resume_link"]


def test_empty_edits_does_not_mark_resume_tailored(monkeypatch, patch_notion_db):
    fake_db = patch_notion_db(stage2_tailor)
    pid = _seed_reviewed(fake_db, "Beta Inc", "beta")
    _patch_common(monkeypatch, {pid: ([], [])})

    stage2_tailor.run(min_score=0)

    rec = fake_db._pages[pid]
    assert rec["status"] != "Resume Tailored"
    assert rec["status"] == "Human Review"
    assert "zero-edit" in rec["notes"].lower()
    # The file is still saved/linked so a human can inspect the (unmodified) copy.
    assert rec["tailored_resume_link"]


def test_empty_edits_appends_to_existing_notes(monkeypatch, patch_notion_db):
    fake_db = patch_notion_db(stage2_tailor)
    pid = _seed_reviewed(fake_db, "Beta Inc", "beta")
    fake_db._pages[pid]["notes"] = "Pre-existing note."
    _patch_common(monkeypatch, {pid: ([], [])})

    stage2_tailor.run(min_score=0)

    assert fake_db._pages[pid]["notes"].startswith("Pre-existing note.\n")


def test_mixed_batch_only_zero_edit_job_is_held_back(monkeypatch, patch_notion_db):
    fake_db = patch_notion_db(stage2_tailor)
    pid_ok = _seed_reviewed(fake_db, "Acme Corp", "acme")
    pid_zero = _seed_reviewed(fake_db, "Beta Inc", "beta")
    _patch_common(monkeypatch, {
        pid_ok: ([{"old": "x", "new": "y", "reason": "r"}], ["kw1"]),
        pid_zero: ([], []),
    })

    stage2_tailor.run(min_score=0)

    assert fake_db._pages[pid_ok]["status"] == "Resume Tailored"
    assert fake_db._pages[pid_zero]["status"] == "Human Review"
