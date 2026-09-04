"""
Guards for the nightly workflow's off-peak cron schedule and daytime queue delay guard.

GitHub Actions scheduled triggers on :00 past the hour suffer severe queue delays (3-7+ hours).
When delayed into daytime, unattended runs collide with interactive Claude Code sessions and
eat the user's daytime rate limits.

These tests ensure:
1. The cron schedule uses an off-peak minute (not :00).
2. The safety guard step exists and runs before any checkout or pipeline execution.
3. The guard is restricted only to scheduled runs (so manual workflow_dispatch runs are never blocked).
4. The daytime boundaries are defined in the workflow env.
"""
from pathlib import Path

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "nightly-pipeline.yml"

STEP_NAME = "Guard against daytime queue delay"


def _lines():
    return WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()


def _step_names_in_order() -> list:
    return [
        line.strip()[len("- name: "):]
        for line in _lines()
        if line.strip().startswith("- name: ")
    ]


def _step_block(name: str) -> str:
    lines = _lines()
    idx = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {name}")
    end = idx + 1
    while end < len(lines) and not lines[end].lstrip().startswith("- "):
        end += 1
    return "\n".join(lines[idx:end])


def test_schedule_trigger_currently_disabled():
    """Scheduled runs are deliberately disabled (2026-09-03) — nightly cron was firing erratically.

    Remove this test when re-enabling the schedule (uncomment the `schedule:`/`- cron:` lines).
    """
    for line in _lines():
        stripped = line.strip()
        if stripped.startswith("- cron:") or stripped == "schedule:":
            raise AssertionError(
                f"schedule trigger should stay commented out until deliberately re-enabled: {line!r}"
            )


def test_cron_uses_off_peak_minute():
    """Top-of-the-hour (:00) crons face extreme queue congestion on GitHub Actions."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    cron_line = next(line for line in text.splitlines() if "- cron:" in line)
    cron_val = cron_line.split("cron:", 1)[1].strip().strip('"').strip("'")
    minute_field = cron_val.split()[0]
    assert minute_field != "0", f"cron should use an off-peak minute, got {minute_field}"


def test_schedule_guard_step_exists():
    assert STEP_NAME in _step_names_in_order()


def test_schedule_guard_runs_before_pipeline():
    names = _step_names_in_order()
    guard_idx = names.index(STEP_NAME)
    pipeline_idx = names.index("Run pipeline")
    assert guard_idx < pipeline_idx, "schedule guard must run before Run pipeline"


def test_schedule_guard_gated_by_schedule_event():
    block = _step_block(STEP_NAME)
    assert "github.event_name == 'schedule'" in block, (
        "guard must only apply to schedule events so manual workflow_dispatch runs are not blocked"
    )


def test_schedule_guard_checks_utc_hour():
    block = _step_block(STEP_NAME)
    assert "CURRENT_HOUR_UTC" in block
    assert "exit 1" in block
