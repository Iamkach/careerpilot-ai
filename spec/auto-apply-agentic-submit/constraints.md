# Constraints

- **The eligibility/sponsorship/salary/yes-no-legal answer tool must have no free-form
  value/answer parameter in its signature or exposed schema.** There must be no argument position
  through which an agent could pass a composed answer for these fields, under any tool-call
  sequence. This is enforced by the function signature, not by prompt wording, and must hold for
  every backend (Claude Agent SDK and OpenRouter alike).
- **There is no generic "type text into any selector" tool.** Only `locate_and_fill_field` (which
  ignores any agent-supplied value when a plan entry exists, and refuses eligibility-shaped labels
  it has no plan entry for) and `attach_resume` (which always uses Layer 1's resolved resume path,
  never an agent-supplied path) exist as write-capable tools.
- **`submit()` re-validates against actually-confirmed-filled state at click time**, not the
  model's self-report of what it did. A required field the model believes it filled but never
  actually confirmed on the live page blocks the submit call.
- **`submit()` is the only call site of a submit click in the entire codebase.** No second path,
  no flag-gated alternative inside `autoapply_browser.py` (Layer 2's no-submit invariant for the
  non-agentic path is unchanged and still true).
- **`Applied` is written only after an observed, verified post-submit confirmation signal** (URL
  change away from the form, or confirmation-page text) — never on "the submit tool call returned
  ok." A submit that reports success but shows no observable confirmation is treated as a block,
  not a success.
- **A blocked job must requeue, bounded by an attempts ceiling** (`MAX_AUTOAPPLY_ATTEMPTS`,
  following the existing `MAX_SCORING_ATTEMPTS`/`MAX_ENRICHMENT_ATTEMPTS` convention) — never
  retried forever, never dead-ended on the first failure.
- **Layer 1 runs to completion before the agent loop starts**, and its resolved answers are never
  re-decided by the agent — the agent is an interaction engine over a pre-computed answer set.
- **Agent runtime selection must compose with the existing `AI_PROVIDER`/`FAST_PROVIDER`/
  `QUALITY_PROVIDER`/`--ai-mode` mechanism** in `scripts/utils.py`/`config/settings.py`/`run.py` —
  no parallel provider-selection system.
- **Two independent gates before any real submit can fire**: `AUTOAPPLY_AGENTIC_ENABLED` (config)
  and `--agent` (CLI flag) must both be set; a further `AUTOAPPLY_AGENT_REAL_SUBMIT` (config,
  default off) must be explicitly enabled before `submit()` performs a real click rather than a
  dry-run screenshot-and-log.
- **`AUTOAPPLY_DAILY_CAP` remains the only cap on submissions per run** — no new rate-limit
  mechanism introduced.
