# Plan

## Files

- **New: `scripts/autoapply_agent_tools.py`** — the guarded tool implementations; the entire
  safety property rests on this file. SDK-agnostic (dispatched identically by both backends).

  ```python
  class AgentSession:
      """One application attempt's live state: the Playwright page, Layer 1's plan
      (read-only from here on), and a running ledger of which planned required fields
      were actually confirmed filled on THIS page — the source of truth submit()
      checks, independent of what the model claims happened."""
      def __init__(self, page, plan: dict, resume_path: str):
          self.page = page
          self.plan = plan
          self.resume_path = resume_path
          self.confirmed: dict[str, dict] = {}
          self.resolved_by: dict[str, int] = {}

  def _plan_entry_for_label(session, label: str) -> dict | None: ...
      # fuzzy-matches against session.plan["fields"], same matching style as
      # _label_matches_pattern in autoapply.py

  def get_eligibility_answer(field_label: str) -> dict:
      """THE GUARDED TOOL. No `value`/`answer` parameter exists in this function's
      signature or its exposed JSON schema — no argument position through which an
      agent could pass a composed answer. Returns the plan's pre-resolved value
      verbatim, or a block signal. Never calls ai_chat(). Never accepts free text."""
      entry = _plan_entry_for_label(_SESSION, field_label)
      if entry is None:
          # live-only field (schema_known=False channel) — re-classify with the
          # SAME rules _resolve_field uses, so eligibility is still caught
          for keys, pkey in _LABEL_RULES:
              if pkey in _ELIGIBILITY_KEYS and any(k in field_label.lower() for k in keys):
                  val = APPLICATION_PROFILE.get(pkey)
                  if val is None:
                      return {"status": "blocked", "reason": "eligibility unset — never guessed"}
                  return {"status": "ready", "value": bool(val), "source": f"profile.{pkey}"}
          return {"status": "blocked", "reason": "not a recognized eligibility field"}
      if entry["status"] != "ready":
          return {"status": "blocked", "reason": entry.get("source", "unresolved")}
      return {"status": "ready", "value": entry["value"], "source": entry["source"]}

  def locate_and_fill_field(field_label: str, value: str | None = None) -> dict:
      """Reuses Phase 1+2's _find() tier walk from autoapply_browser.py verbatim.
      (1) label matches a plan entry -> `value` param IGNORED entirely, plan's own
          resolved value used regardless of what the agent passed.
      (2) live-only label -> `value` accepted only if a live classifier confirms the
          label isn't eligibility/sponsorship/salary/yes-no-legal shaped; otherwise
          refused, directing the agent to get_eligibility_answer() instead (which
          will itself block on it)."""

  def attach_resume(field_label: str) -> dict: ...
      # resume path is ALWAYS session.resume_path; agent supplies only a label

  def submit() -> dict:
      """Second, code-level gate. Cross-checks every REQUIRED plan field against
      session.confirmed (not the model's self-report) before the actual click.
      Only call site of a submit click in the entire codebase."""
      required = [f for f in _SESSION.plan["fields"] if f["required"]]
      missing = [f["label"] for f in required
                 if f["label"] not in _SESSION.confirmed and f["status"] != "review_required" is False]
      if missing:
          return {"ok": False, "reason": f"blocked — unresolved required field(s): {missing}"}
      _SESSION.page.click(_find_submit_control(_SESSION.page))
      return {"ok": True}

  def give_up(reason: str) -> dict: ...
      # voluntary bail (captcha, unresolvable live-only free-text) -> requeue path
  ```

  Full tool list exposed to the model: `navigate(url)`, `read_page()` (accessibility-tree-style
  snapshot of visible fields/labels/`required` attrs), `locate_and_fill_field`,
  `get_eligibility_answer`, `attach_resume`, `screenshot()`, `submit()`, `give_up(reason)`.
  Deliberately **no** generic "type text into this selector" tool.

- **New: `scripts/autoapply_agent.py`** — the dual-backend agent loop.
  - **Backend A (Claude, metered or subscription)** via `claude-agent-sdk`'s custom-tool API
    (`@tool` decorator + `create_sdk_mcp_server(name="autoapply", tools=[...])`), driven through a
    real multi-turn `ClaudeSDKClient` session (not the one-shot `max_turns=1` pattern
    `_sdk_text()` uses for stages 1–6 — this needs an actual loop). `ClaudeAgentOptions(
    mcp_servers={"autoapply": server}, allowed_tools=["mcp__autoapply__..."], max_turns=N)`.
    Metered-vs-subscription selection reuses `_chat_claude_code`'s existing
    `os.environ.pop("ANTHROPIC_API_KEY", ...)` pattern.
  - **Backend B (OpenRouter, incl. free-tier)** — bespoke tool-use loop against
    `chat.completions.create(tools=[...], tool_choice="auto")`, reusing `_chat_openrouter`'s
    `openai.OpenAI(base_url="https://openrouter.ai/api/v1")` client shape (the Agent SDK has no
    OpenRouter transport). Loop: send messages+schemas → dispatch `tool_calls` to the same
    `autoapply_agent_tools` functions → append `role: "tool"` results → repeat until a final text
    turn or `submit`/`give_up`.
  - Tool schemas generated once from a shared registry (`AGENT_TOOL_SPECS` in
    `autoapply_agent_tools.py`) and adapted per backend, so tool *behavior* (and the guard) never
    forks — only calling convention does.
  - In-process function dispatch, not an out-of-process MCP server over stdio/SSE — the tools need
    direct synchronous access to the live Playwright `page` and the in-memory `AgentSession`
    ledger `submit()` checks; serializing across a process boundary adds a failure surface for no
    benefit here.
  - `run_agentic_apply(job, plan, rpt, channel, headless) -> dict` — single entry point. Reuses
    `fill_application()`'s launch/navigate/`_classify_block()` captcha-or-auth pre-check unchanged.
    Returns the same result shape Layer 2 returns today (`ok, outcome, detail, filled, screenshot,
    resolved_by`) plus `submitted: bool`, `applied_verified: bool`.
  - New `_classify_confirmation(page) -> bool` (mirrors `_classify_block()`'s shape) — checks for a
    URL change away from the apply form or confirmation-page text hints ("application received",
    "thank you for applying", "we've received your application") after `submit()` reports
    `ok: True`. `Applied` is written **only** when this returns true.
  - New `_requeue_or_terminal(job, reason, channel)` — the single funnel for every non-terminal
    block (pre-loop readiness block, in-loop `give_up()`, submit-without-confirmation). Under
    `MAX_AUTOAPPLY_ATTEMPTS`: reverts status to `Resume Tailored` with incremented `apply_attempts`
    and a logged note. Over the ceiling: falls to terminal `Needs Human: Question`, matching every
    other attempt-capped path in this repo (`MAX_SCORING_ATTEMPTS`, `MAX_ENRICHMENT_ATTEMPTS`).

- **Modify: `scripts/autoapply.py`**
  - New `_agent_apply_one(job, plan, rpt, channel)` — wraps `run_agentic_apply()` the same
    never-raises way `_fill_one()` wraps `fill_application()` today.
  - `run()` gains a branch: when `channel in FILLABLE_CHANNELS and fill and agent_mode`, call
    `_agent_apply_one()` instead of `_fill_one()`.
  - New `AGENT_WRITABLE_STATUSES = WRITABLE_STATUSES | {"Applied"}` used **only** inside
    `autoapply_agent.py` — **not** merged into this module's own `WRITABLE_STATUSES`, so the
    existing non-agentic invariant test (`Applied` never in `WRITABLE_STATUSES`) stays meaningful
    and unmodified.

- **No change: `scripts/autoapply_browser.py`** — `_find()`/`_semantic_locators()`/`_to_locator()`
  (Phase 1+2 of selector-resolution-hardening) are imported and reused as-is by
  `locate_and_fill_field()`. No submit code is added here; the existing no-submit grep test stays
  true and unmodified.

- **Modify: `scripts/utils.py`**
  - New `_resolve_agent_model(provider)` alongside `_resolve_model()`, reading a new `"agent"`
    sibling key in `MODEL_OVERRIDES[provider]` (falling back to that provider's `"quality"` entry,
    then its built-in default).
  - No new `_BACKENDS` entries needed (the agent tier isn't an `ai_chat()` call).

- **Modify: `config/settings.py`**
  - `AGENT_PROVIDER = os.environ.get("AGENT_PROVIDER", "") or QUALITY_PROVIDER`, resolved through
    the existing `_resolve_provider()` no-key-fallback logic.
  - `MAX_AUTOAPPLY_ATTEMPTS` (default e.g. 3), following the `MAX_SCORING_ATTEMPTS` convention.
  - `AUTOAPPLY_AGENTIC_ENABLED` (default `False`).
  - `AUTOAPPLY_AGENT_REAL_SUBMIT` (default `False`, independent of the above).

- **Modify: `run.py`**
  - New `--agent` flag on `--stage 7`, independent of `--fill` (`--fill` alone keeps today's
    stop-before-submit behavior unchanged — the rollout lever, see below).
  - `--dry-run --agent` refuses to navigate/submit: builds the plan, logs the intended action,
    zero Notion writes, zero browser opens — same contract as today's `--dry-run --fill`.
  - `--agent` without `AUTOAPPLY_AGENTIC_ENABLED` set errors with a clear message pointing at the
    setting (second gate, prevents an unreviewed script/CI change from starting real submissions).
  - `stage7()` passes `agent=args.agent` through; banner text updated to reflect mode.
  - Extend `_AI_MODE_PROVIDERS` (backing `--ai-mode`) to also set `AGENT_PROVIDER` alongside
    `FAST_PROVIDER`/`QUALITY_PROVIDER` — `hybrid` puts the agent tier on `claude_code`.

- **Modify: `CLAUDE.md`** (required in the same change per this repo's Definition of Done):
  1. Project Overview stage-7 row: replace "optionally pre-fill... **Never submits**" with a
     description of both modes (`--fill` = pre-fill only, unchanged; `--agent` = full agentic
     fill-and-submit).
  2. Stage 7 section opening line: rewrite the "It never submits" claim precisely — state what
     still never happens autonomously (an eligibility/salary answer composed by the model) vs.
     what now can (the Submit click, gated by `readiness_report()`).
  3. Layer 2 "no submit code path... not behind a flag" bullet: true only for the non-agentic
     path now; add a forward-reference to the new Layer 4 section.
  4. The `"Applied is never inferred"` paragraph: currently states extension confirm-applied is
     *"the only other path"* — rewrite the surviving invariant as "`Applied` is only ever set on
     the basis of an observed, verified signal — never inferred," and list the now-three
     verified-signal sources.
  5. `AUTOAPPLY_DAILY_CAP` paragraph: note it remains the *only* cap on autonomous submissions,
     since no human reviews each one before it fires now.
  6. Common Commands: add `python run.py --stage 7 --agent`.
  7. New "### Layer 4 — agentic submit" section, parallel to "### Layer 3 — browser extension",
     placed directly after the existing Stage 7 section: MCP tool surface, eligibility-guard code
     shape, block→requeue mechanism, `AGENT_PROVIDER` wiring, pointer to this spec folder.
  8. "Switching AI Provider" section: add `AGENT_PROVIDER` to the provider-tier table and the
     "Hybrid tiering" prose.

- **Modify: `spec/selector-resolution-hardening/meta.md`** — `Status: superseded`; Phase 1+2 code
  is reused (not discarded) by `locate_and_fill_field()`; Phase 3 (narrow cached LLM fallback) is
  superseded by this feature's full loop. Add `Superseded-by: auto-apply-agentic-submit`.

- **Modify: `docs/research/agent-browser-landscape.md`** — append a dated addendum noting the
  explicit reversal and linking to this spec's `problem.md`; leave the original analysis intact as
  historical record (it was a reasonable evaluation of a narrower question than the one actually
  decided).

- **Modify: `spec/INDEX.md`** — add the new row.

- **New/modify tests** — see `verification.md`.

## Rollout sequencing (engineering staging, not a re-litigation of "no approval gate")

1. Build behind `AUTOAPPLY_AGENTIC_ENABLED=False` + `--agent` — both required, nothing changes for
   anyone until both are explicitly set.
2. Ship the dry-submit mode first (`AUTOAPPLY_AGENT_REAL_SUBMIT=False` even with agentic enabled):
   `submit()`'s real `page.click(...)` is replaced with a screenshot + log + `{ok: True, dry:
   True}`; `_classify_confirmation()` is skipped; no `Applied` write. Validates the whole loop
   (discovery, guard behavior, requeue logic) against real live boards with zero submission risk.
3. Flip `AUTOAPPLY_AGENT_REAL_SUBMIT` on only after reviewing a batch of dry-submit runs — start
   with Greenhouse (public schema Layer 1 already leans on), then Lever (schema-unknown, exercises
   the live-only-field defense-in-depth harder).
4. Keep `AUTOAPPLY_DAILY_CAP` low during this validation window (existing setting, no new
   mechanism, just a recommendation).
5. This plan does not recommend `--agent` becoming the default behavior of plain `--fill`.
