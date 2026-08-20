# Problem

`docs/research/agent-browser-landscape.md` (2026-08-10) evaluated moving Stage 7 Layer 2 to an
agentic/MCP browser and concluded against it: none of the four stated reversal triggers ("tiers
still exhaust often after Phase 1", "cloud/CI execution with login-walled boards", "concurrency
rises an order of magnitude", "non-Chromium coverage required") were true at the time, and the
cheapest fix for the then-known failure mode (a hand-rolled selector resolver missing
`aria-label`/`aria-labelledby`/non-adjacent `<label for>` markup) was already inside Playwright
itself via `get_by_label`/`get_by_role`. `spec/selector-resolution-hardening/` Phase 1+2 shipped
exactly that fix on the same day, with Phase 3 (a narrow, cached, last-resort LLM fallback for
exhausted tiers only) explicitly scoped but deferred pending Phase 2 telemetry.

This document records a direct reversal of that conclusion, not a re-derivation of it. The
deterministic ceiling Layer 1/2 hits today is structural, not a selector-tier gap:

- `FILLABLE_CHANNELS = {greenhouse, lever}` — every job on any other channel gets an answer sheet
  only, never filled.
- Lever/Ashby expose no public field schema (`schema_known=False`), so Layer 1 can only plan
  against `GENERIC_QUESTIONS`; anything the live page actually asks beyond that surfaces for the
  first time inside Layer 2's fill pass, where there is no mechanism to *adapt* — only to resolve
  or drift-abort.
- `MIN_RESOLVE_RATIO` drift-aborts rather than partially fills, and Layer 2 has no way to recover
  from a drift outcome other than a human noticing `Needs Human: *` in Notion and intervening by
  hand — there is no requeue, no retry-with-different-strategy.
- Even where fields resolve cleanly, a human still has to open every filled form and click Submit
  themselves — the marginal cost per application never drops to near-zero, which is the stated
  goal this pipeline optimizes for (see `project_apply_throughput_goal` in the maintainer's own
  notes: minutes-per-application, not backlog completeness).

The user has decided that the cost of this manual bottleneck — jobs sitting indefinitely at
`Needs Human: *` pending manual review, and every successfully-filled application still requiring
a human click — now outweighs the risk of autonomous submission, provided the one failure mode
that is genuinely unrecoverable (a wrong eligibility/sponsorship/salary answer submitted to a real
employer) stays mechanically impossible rather than merely discouraged. That is the one invariant
this feature is not allowed to relax; everything else about "never submits" is renegotiable and is
renegotiated here.
