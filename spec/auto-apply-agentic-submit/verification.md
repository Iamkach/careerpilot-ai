# Verification

## Automated

- **Existing tests stay true and pass unmodified** (annotate, don't rewrite the assertions):
  - `tests/test_autoapply_notion.py::test_run_never_writes_applied` and its
    `assert "Applied" not in WRITABLE_STATUSES` — still true because `autoapply.py`'s
    `WRITABLE_STATUSES` is deliberately not touched; `AGENT_WRITABLE_STATUSES` lives only in
    `autoapply_agent.py`. Add a docstring note that this now describes the non-agentic path
    specifically, with a forward-reference to the new agent test files.
  - `tests/test_autoapply_browser.py::test_never_submits_the_form` /
    `test_source_has_no_submit_click` (grep-asserts no submit-click string in
    `autoapply_browser.py`) — stay true unmodified, since the submit click lives only in
    `autoapply_agent_tools.py::submit()`.

- **New `tests/test_autoapply_agent_tools.py`** (default suite, mocked — no browser needed, a fake
  `page`/`AgentSession` suffices):
  - `get_eligibility_answer()` has no `value`/`answer` parameter (introspect signature/schema).
  - Adversarial: `locate_and_fill_field("Will you require visa sponsorship?", value="No")` against
    a session whose plan has that field as live-only (schema_known=False) → refused.
  - `locate_and_fill_field()` ignores an agent-supplied `value` when a plan entry exists, uses the
    plan's value instead.
  - `submit()` refuses when a required field is `ready` in the plan but was never confirmed filled
    on the page (simulates a model that "forgot" a field).
  - Grep-style test: submit-click code exists in exactly `autoapply_agent_tools.py::submit()` and
    nowhere else reachable from the model.
  - `_requeue_or_terminal()`: attempt count under/over `MAX_AUTOAPPLY_ATTEMPTS` produces
    `Resume Tailored` vs. the terminal `Needs Human` status, with correct logged notes.

- **New `tests/test_autoapply_agent.py`** (mostly mocked backend loop — fake tool-call sequences,
  not a real LLM call — plus a `browser`-marked subset against `tests/fixtures/greenhouse_form.html`):
  - Full happy path: agent loop → `submit()` → `_classify_confirmation()` true → `Applied` written
    with the correct "autonomous agent submit" audit-line label.
  - Submit-without-confirmation: `submit()` returns ok but the fixture never navigates away →
    falls to requeue; `Applied` NOT written.
  - `AUTOAPPLY_DAILY_CAP` still caps agent-mode attempts per run identically to today's cap.
  - Both backends (Agent-SDK path and OpenRouter tool-loop path) exercised against the same fake
    tool-call sequence, asserting identical guard behavior — proves the guard isn't backend-specific.

- Extend the existing LinkedIn/Indeed-never-fillable test to also assert `--agent` mode respects
  `FILLABLE_CHANNELS`.

- `pytest -v` (fast suite) and `pytest -m browser` both green before calling any phase done.

## Manual

1. `python run.py --stage 7 --agent --dry-run --limit 3` against real `Resume Tailored` jobs —
   confirm plans build, zero Notion writes, zero browser opens.
2. With `AUTOAPPLY_AGENTIC_ENABLED=True`, `AUTOAPPLY_AGENT_REAL_SUBMIT=False`, run
   `--stage 7 --agent` headed against a real Greenhouse job — watch the loop navigate/fill/attempt
   submit, confirm a dry-submit screenshot is produced and no Notion status moves to `Applied`.
3. Adversarial check: temporarily blank `APPLICATION_PROFILE["work_authorized"]` and confirm the
   run requeues that job with a `blocked` note rather than guessing or submitting.
4. Repeat 1–3 against a Lever job (schema-unknown channel) to exercise the live-only-field
   defense-in-depth path.
5. Only after 1–4 are trusted: flip `AUTOAPPLY_AGENT_REAL_SUBMIT=True` on one low-stakes job and
   confirm `Applied` is written with the correct audit-log line only after a real observed
   confirmation on the live page.
6. Confirm `--ai-mode metered --metered-provider openrouter` (a free-tier model) drives the loop
   end-to-end at least once, and that `--ai-mode subscription`/`hybrid` also work.
7. `python scripts/dev_check.py` clean before calling the change done.
