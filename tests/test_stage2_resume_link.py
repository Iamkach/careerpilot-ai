"""
Tests for _tailored_resume_link() — the nightly-workflow residual gap fix.

Local runs write a file:// URI to Notion's Tailored Resume Link, which is dead once the
GitHub Actions runner's filesystem is discarded. Under GITHUB_ACTIONS, the link instead
points at the tailored-resumes orphan branch the nightly workflow publishes to
(.github/workflows/nightly-pipeline.yml's "Publish tailored resumes" step), via a
raw.githubusercontent.com URL that doesn't expire — so Stage 4's digest and Stage 7's
resolve_tailored_resume() (scripts/autoapply.py) both stay working for a CI-tailored job.
"""
from pathlib import Path

from scripts import stage2_tailor
from scripts.stage2_tailor import _tailored_resume_link
from scripts.utils import ROOT


def test_local_run_writes_file_uri(monkeypatch):
    """No GITHUB_ACTIONS set — behavior must match today's local output exactly."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    path = str(ROOT / "output" / "resumes" / "2026-07-26_Acme_Engineer.docx")

    result = _tailored_resume_link(path)

    assert result == f"file://{Path(path).resolve()}"


def test_ci_run_writes_raw_githubusercontent_url(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "someuser/careerpilot-ai")
    path = str(ROOT / "output" / "resumes" / "2026-07-26_Acme_Engineer.docx")

    result = _tailored_resume_link(path)

    assert result == (
        "https://raw.githubusercontent.com/someuser/careerpilot-ai/"
        "tailored-resumes/output/resumes/2026-07-26_Acme_Engineer.docx"
    )
