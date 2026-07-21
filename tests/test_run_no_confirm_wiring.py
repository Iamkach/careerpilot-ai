"""
PR #11 review item #5 — nightly-pipeline.yml's `stage3`/`stage5` workflow_dispatch modes
call `python run.py --stage 3` / `--stage 5` with no way to avoid the underlying stage's
input() calls, which crash with EOFError against CI's closed stdin. run.py now has a
`--no-confirm` flag; this file proves run.py's stage3()/stage5() wrapper functions actually
thread it through to the stage scripts' run() calls (the fix is only real if the plumbing
connects all the way from the CLI flag to the stage's `no_confirm` parameter).
"""
import argparse

import run


def _args(**overrides):
    base = dict(
        company=None, role="", contact=None, contact_role="",
        jd_file="", hm_linkedin="", no_confirm=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_stage3_threads_no_confirm_through_to_stage3_outreach_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.stage3_outreach.run",
        lambda **kwargs: calls.append(kwargs),
    )

    run.stage3(_args(company="Acme Corp", no_confirm=True))

    assert len(calls) == 1
    assert calls[0]["no_confirm"] is True
    assert calls[0]["target_company"] == "Acme Corp"


def test_stage3_defaults_no_confirm_false_for_interactive_use(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.stage3_outreach.run",
        lambda **kwargs: calls.append(kwargs),
    )

    run.stage3(_args(no_confirm=False))

    assert calls[0]["no_confirm"] is False


def test_stage5_threads_no_confirm_through_to_stage5_interview_prep_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.stage5_interview_prep.run",
        lambda **kwargs: calls.append(kwargs),
    )

    run.stage5(_args(company="Acme Corp", no_confirm=True))

    assert len(calls) == 1
    assert calls[0]["no_confirm"] is True
    assert calls[0]["company"] == "Acme Corp"


def test_stage5_defaults_no_confirm_false_for_interactive_use(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.stage5_interview_prep.run",
        lambda **kwargs: calls.append(kwargs),
    )

    run.stage5(_args(company="Acme Corp", no_confirm=False))

    assert calls[0]["no_confirm"] is False
