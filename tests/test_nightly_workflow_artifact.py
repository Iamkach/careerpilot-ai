"""
The nightly workflow must publish output/ as a run artifact, or every file the pipeline
produces (tailored .docx resumes, outreach drafts, digest/prep/negotiation HTML, stage 7
answer sheets) dies with the runner's filesystem and there is no way to retrieve a nightly
run's work at all.

Same plain grep-style approach as tests/test_nightly_workflow_no_confirm.py: this guards a
*config* property, so it asserts against the YAML text rather than mocking anything.

The `if: always()` assertion is the one that earns its keep. It's the property most likely to
be dropped silently while tidying the workflow, and losing it costs you the output from
exactly the failed runs worth inspecting — a green-run-only upload looks fine right up until
the night you need it.
"""
from pathlib import Path

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "nightly-pipeline.yml"

UPLOAD_ACTION = "actions/upload-artifact"


def _is_upload_directive(line: str) -> bool:
    """True only for a real `uses: actions/upload-artifact@vN` step directive — not a passing
    mention of the action name in a comment, which would otherwise anchor the block scan to
    whatever step the comment happens to sit under."""
    stripped = line.strip().lstrip("- ").strip()
    return stripped.startswith("uses:") and UPLOAD_ACTION in stripped


def _upload_step_block() -> str:
    """The upload step's YAML block: from the `uses: actions/upload-artifact` line back to the
    step's `- name:` and forward to the next step (or EOF). Returned as text so the assertions
    below can stay grep-style without taking a YAML parser dependency."""
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    idx = next(i for i, line in enumerate(lines) if _is_upload_directive(line))

    start = idx
    while start > 0 and not lines[start].lstrip().startswith("- "):
        start -= 1

    end = idx + 1
    while end < len(lines) and not lines[end].lstrip().startswith("- name:"):
        end += 1

    return "\n".join(lines[start:end])


def test_workflow_uploads_output_as_artifact():
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    assert any(_is_upload_directive(line) for line in lines), (
        "nightly workflow no longer uploads output/ — a run's resumes and drafts would be "
        "discarded with the runner"
    )


def test_artifact_path_covers_output_dir():
    block = _upload_step_block()
    assert "path:" in block
    path_line = next(line for line in block.splitlines() if line.strip().startswith("path:"))
    assert "output" in path_line, f"upload step does not cover output/: {path_line!r}"


def test_artifact_uploads_even_when_pipeline_fails():
    block = _upload_step_block()
    assert "if: always()" in block, (
        "upload step lost `if: always()` — output from failed runs, the runs most worth "
        "diagnosing, would no longer be retrievable"
    )


def test_missing_output_dir_does_not_fail_the_run():
    """`if: always()` means this step can run after a failure that happened before output/ was
    ever created (e.g. `Verify setup`). Without this, upload-artifact's default would flag it
    and muddy the run's status."""
    block = _upload_step_block()
    assert "if-no-files-found: warn" in block
