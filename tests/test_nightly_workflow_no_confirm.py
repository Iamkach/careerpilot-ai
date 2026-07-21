"""
PR #11 review item #5 — the nightly workflow's `stage3`/`stage5` workflow_dispatch modes
must pass --no-confirm, or they crash on input() against CI's closed stdin (see
tests/test_stage5_no_confirm.py and tests/test_run_no_confirm_wiring.py for the code-level
fix this config change depends on). A plain grep-style assertion here catches the case
where someone edits the workflow's case statement back to the old bare `--stage 3`/`--stage
5` invocations without noticing why --no-confirm was there.
"""
from pathlib import Path

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "nightly-pipeline.yml"


def test_stage3_dispatch_passes_no_confirm():
    text = WORKFLOW_PATH.read_text()
    stage3_line = next(line for line in text.splitlines() if "stage3)" in line)
    assert "--no-confirm" in stage3_line


def test_stage5_dispatch_passes_no_confirm():
    text = WORKFLOW_PATH.read_text()
    stage5_line = next(line for line in text.splitlines() if "stage5)" in line)
    assert "--no-confirm" in stage5_line
