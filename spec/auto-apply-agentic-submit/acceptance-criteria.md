# Acceptance criteria

- [ ] A field classified eligibility/sponsorship/salary/yes-no-legal by `_LABEL_RULES` (or the
      live-page classifier for schema-unknown channels) cannot be filled with agent-composed text
      under any tool-call sequence — proven by an adversarial test that tries.
- [ ] `get_eligibility_answer`'s function signature/tool schema has no `value`/`answer` parameter.
- [ ] `locate_and_fill_field` ignores an agent-supplied `value` whenever a Layer 1 plan entry
      exists for that label, using the plan's resolved value instead.
- [ ] `submit()` refuses to click when any required field is `ready` in the plan but was never
      actually confirmed filled on the live page in this session.
- [ ] `submit()` is the only call site of a form-submit click reachable from the model, in
      `autoapply_agent_tools.py`; `autoapply_browser.py` still contains no submit-click code path
      at all (existing grep-style test unmodified and still green).
- [ ] `Applied` is set by the agentic path only after `_classify_confirmation()` returns true; a
      submit that reports `ok: True` with no observed confirmation does not write `Applied`.
- [ ] `Applied`'s `Application Log` audit line for the agentic path is distinguishable from the
      existing human/extension-confirmed line (labelled "autonomous agent submit").
- [ ] A job that exhausts `MAX_AUTOAPPLY_ATTEMPTS` lands on a terminal `Needs Human` status, never
      loops forever; a job under the ceiling is requeued to `Resume Tailored` with an incremented
      attempt count and a logged reason.
- [ ] `--ai-mode subscription` / `metered` / `hybrid` (with `--metered-provider openrouter`) each
      successfully drive the agent loop end-to-end against the same fixture, with identical guard
      behavior across backends.
- [ ] With `AUTOAPPLY_AGENTIC_ENABLED=False` (the default) or `--agent` omitted, Stage 7 behavior
      is byte-for-byte unchanged from today.
- [ ] With `AUTOAPPLY_AGENT_REAL_SUBMIT=False`, a full agent run against a real live form produces
      a screenshot and log entry but performs no real click and writes no `Applied` status.
- [ ] LinkedIn/Indeed remain unreachable by the agentic path exactly as they are by Layer 2 today.
