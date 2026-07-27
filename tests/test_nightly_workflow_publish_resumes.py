"""
The nightly workflow must publish output/resumes/*.docx to the tailored-resumes branch, or
Stage 2's raw.githubusercontent.com link (scripts/stage2_tailor.py::_tailored_resume_link())
points at nothing — same grep-over-YAML-text approach as test_nightly_workflow_artifact.py,
no YAML parser dependency, since this guards specific config properties/ordering rather than
full schema validity.
"""
from pathlib import Path

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "nightly-pipeline.yml"

STEP_NAME = "Publish tailored resumes to tailored-resumes branch"


def _lines():
    return WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()


def _step_block(name: str) -> str:
    """The named step's YAML block: from its `- name:` line to the next `- name:`/`- uses:`
    step or EOF. Returned as text so assertions stay grep-style."""
    lines = _lines()
    idx = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {name}")
    end = idx + 1
    while end < len(lines) and not lines[end].lstrip().startswith("- "):
        end += 1
    return "\n".join(lines[idx:end])


def _step_names_in_order() -> list:
    return [
        line.strip()[len("- name: "):]
        for line in _lines()
        if line.strip().startswith("- name: ")
    ]


def test_workflow_grants_contents_write_permission():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "permissions:" in text
    assert "contents: write" in text, (
        "nightly workflow has no contents: write permission — the publish-resumes step's "
        "git push would 403 against the default GITHUB_TOKEN scope"
    )


def test_publish_step_exists():
    assert STEP_NAME in _step_names_in_order()


def test_publish_step_runs_after_pipeline_and_before_artifact_upload():
    names = _step_names_in_order()
    pipeline_idx = names.index("Run pipeline")
    publish_idx = names.index(STEP_NAME)
    upload_idx = names.index("Bundle run output")
    assert pipeline_idx < publish_idx < upload_idx, (
        "publish-resumes step must run after the pipeline produces output/resumes/ and "
        "before/alongside the artifact bundle, not before either exists"
    )


def test_publish_step_pushes_to_tailored_resumes_branch():
    block = _step_block(STEP_NAME)
    assert "tailored-resumes" in block
    assert "git push" in block


def test_publish_step_uses_github_token_not_a_new_secret():
    block = _step_block(STEP_NAME)
    assert "GITHUB_TOKEN" in block or "github.token" in block
    # No secrets.* reference beyond the ones already used elsewhere in the workflow file for
    # unrelated purposes — this step specifically must not introduce a new credential.
    assert "secrets." not in block


def test_publish_step_guards_missing_output_dir():
    block = _step_block(STEP_NAME)
    assert "output/resumes" in block
    assert "exit 0" in block, (
        "step must no-op (not fail) when a scrape-only run left output/resumes/ empty or absent"
    )
