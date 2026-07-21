"""
docs/TODO.md "Open for review" item #5 — every run.py CLI path must report a failed Notion
read as a clean message + non-zero exit, not a raw traceback. Only --ingest did before; this
proves --retry-only, --evaluate, and --stage 2 now do too, via the single typed-error guard
at the top of main()'s dispatch.

The guard catches ONLY scripts.utils.NotionReadError (a RuntimeError subclass raised by
_query_db on a read failure). Unrelated RuntimeErrors — Apify failures (scripts/sources.py),
provider/CLI setup, stage 5 — are deliberately NOT caught, so they keep their existing
behavior instead of being mislabeled as a tracker read failure (last test guards that line).
"""
import sys

import pytest

import run
from scripts.utils import NotionReadError


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as excinfo:
        run.main()
    return excinfo


def _assert_clean_abort(excinfo, capsys):
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "could not read the Notion tracker" in out
    # A clean abort must not read as a successful empty run.
    assert "complete" not in out.lower()


def test_retry_only_reports_read_failure_cleanly(monkeypatch, capsys):
    monkeypatch.setattr("scripts.utils.load_resume", lambda: "resume")

    def boom(resume):
        raise NotionReadError("db_get_jobs('Retry') read failed: 503")

    monkeypatch.setattr("scripts.stage1_scrape.rescore_retry_jobs", boom)
    _assert_clean_abort(_run_main(monkeypatch, ["run.py", "--retry-only"]), capsys)


def test_evaluate_reports_read_failure_cleanly(monkeypatch, capsys):
    def boom(**kwargs):
        raise NotionReadError("db_get_jobs('Reviewed') read failed: 503")

    monkeypatch.setattr("scripts.stage2_tailor.run", boom)
    _assert_clean_abort(_run_main(monkeypatch, ["run.py", "--evaluate"]), capsys)


def test_stage2_reports_read_failure_cleanly(monkeypatch, capsys):
    def boom(**kwargs):
        raise NotionReadError("db_get_jobs('Reviewed') read failed: 503")

    monkeypatch.setattr("scripts.stage2_tailor.run", boom)
    _assert_clean_abort(_run_main(monkeypatch, ["run.py", "--stage", "2"]), capsys)


def test_non_read_runtime_error_is_not_swallowed(monkeypatch):
    """A plain RuntimeError (e.g. an Apify failure) must NOT be caught and mislabeled as a
    Notion read failure — it keeps propagating (the run still fails non-zero, but with the
    real error) exactly as before this guard existed."""
    def boom(**kwargs):
        raise RuntimeError("Apify run FAILED")

    monkeypatch.setattr("scripts.stage2_tailor.run", boom)
    monkeypatch.setattr(sys, "argv", ["run.py", "--stage", "2"])
    with pytest.raises(RuntimeError, match="Apify run FAILED"):
        run.main()
