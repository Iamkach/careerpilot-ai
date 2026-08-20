# Non-goals

- **Layer 3 (extension/bridge) is untouched.** No change to `extension/`, `scripts/autoapply_server.py`,
  `identify_job()`, or the `/plan` / `/drafts` / `/confirm-applied` bridge. This feature is Layer 2
  only — human-in-the-loop live filling stays exactly as it is.
- **`FILLABLE_CHANNELS` does not expand.** Still `{greenhouse, lever}`. LinkedIn/Indeed remain
  answer-sheet-only, agentic or not — that exclusion is a ToS/detection-risk rule, not a
  capability gap this feature is meant to close.
- **No new human-approval gate.** Already decided: submission is gated only by
  `readiness_report()`'s existing blocking verdict and `AUTOAPPLY_DAILY_CAP`. This feature does not
  introduce a per-job opt-in, a confirmation prompt, or a review queue before submit.
- **No change to `AUTOAPPLY_DAILY_CAP` semantics** — it remains the sole rate limiter on
  submissions per run; this feature does not add a second cap or remove the existing one.
- **Provider support limited to Claude (metered + subscription) and OpenRouter** for this pass —
  Gemini/Codex function-calling backends for the agent loop are deferred, not built here, even
  though `ai_chat()`'s `_BACKENDS` dict supports them for stages 1–6.
- **No out-of-process MCP server.** The tool surface is MCP-*shaped* (schemas, tool-call
  semantics) but dispatched in-process against a live Playwright page — no stdio/SSE transport,
  no separate server process to operate or fail independently.
- **No change to Layer 1's answer-resolution logic itself** (`_resolve_field`, `_LABEL_RULES`,
  `COMMON_QUESTION_PRESETS`) — the agent consumes Layer 1's output, it does not change how Layer 1
  produces it.
