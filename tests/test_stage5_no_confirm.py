"""
PR #11 review item #5 — scripts/stage5_interview_prep.py's run() called input() to ask for
a manually-pasted JD whenever no cached JD/URL was available, unconditionally. In an
unattended run (e.g. the nightly workflow's `stage5` dispatch mode) stdin is /dev/null, so
that call raises EOFError and crashes the job every time it's invoked without a JD source.

run() now takes a no_confirm flag: when set and no JD source is available, it raises a
clear RuntimeError instead of blocking on input().
"""
import pytest

import scripts.stage5_interview_prep as stage5


def _stub_common(monkeypatch, tmp_path, job=None):
    monkeypatch.setattr(stage5, "load_resume", lambda: "RESUME TEXT")
    monkeypatch.setattr(stage5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(stage5, "get_job_from_notion", lambda company: job)
    monkeypatch.setattr(stage5, "db_get_job_description", lambda pid: None)
    monkeypatch.setattr(stage5, "db_update_status", lambda *a, **k: None)
    monkeypatch.setattr(stage5, "PREP_GUIDES_DIR", str(tmp_path))


def test_run_raises_clear_error_instead_of_blocking_when_no_confirm_and_no_jd_source(monkeypatch, tmp_path):
    _stub_common(monkeypatch, tmp_path, job={"company": "Acme Corp", "title": "Engineer", "url": "", "page_id": "p1"})

    with pytest.raises(RuntimeError, match="No JD available"):
        stage5.run(company="Acme Corp", no_confirm=True)


def test_run_raises_clear_error_when_no_confirm_and_no_job_found_at_all(monkeypatch, tmp_path):
    # get_job_from_notion returns None -> run() builds a bare job dict with no url/page_id,
    # so the "else" branch (no page_id, no url) is what must raise instead of blocking.
    _stub_common(monkeypatch, tmp_path, job=None)

    with pytest.raises(RuntimeError, match="No JD available"):
        stage5.run(company="Ghost Inc", no_confirm=True)


def test_run_still_prompts_interactively_when_no_confirm_is_false(monkeypatch, tmp_path):
    _stub_common(monkeypatch, tmp_path, job={"company": "Acme Corp", "title": "Engineer", "url": "", "page_id": "p1"})
    monkeypatch.setattr(stage5, "generate_prep_guide", lambda job, jd, hm_li, resume: "guide markdown")
    monkeypatch.setattr(stage5, "render_html", lambda md, job: "<html></html>")

    import builtins
    monkeypatch.setattr(builtins, "input", lambda prompt: "pasted JD text")

    stage5.run(company="Acme Corp", no_confirm=False)  # must not raise


def test_run_with_jd_file_never_needs_no_confirm_at_all(monkeypatch, tmp_path):
    _stub_common(monkeypatch, tmp_path, job={"company": "Acme Corp", "title": "Engineer", "url": "", "page_id": "p1"})
    monkeypatch.setattr(stage5, "generate_prep_guide", lambda job, jd, hm_li, resume: "guide markdown")
    monkeypatch.setattr(stage5, "render_html", lambda md, job: "<html></html>")

    jd_file = tmp_path / "jd_input.txt"
    jd_file.write_text("A real job description.")

    stage5.run(company="Acme Corp", jd_file=str(jd_file), no_confirm=True)  # must not raise
