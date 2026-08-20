# Selector resolution hardening (Stage 7 Layer 2)

**Status:** superseded (Phase 1-2 implemented and reused; Phase 3 superseded)
**Priority:** P2
**Size:** S
**Depends-on:** []
**Superseded-by:** auto-apply-agentic-submit

Phase 1-2 (accessibility-tree selector tier + `resolved_by` telemetry) shipped and is reused as-is
by `locate_and_fill_field()` in the superseding feature. Phase 3 (a narrow, cached, last-resort LLM
fallback for exhausted tiers) was scoped but never built — it is superseded by
`spec/auto-apply-agentic-submit/`'s full agentic loop rather than being built separately.

Widens `scripts/autoapply_browser.py`'s field resolver with an accessibility-tree tier
(`aria-label`, `aria-labelledby`, non-adjacent `<label for>`) and per-tier resolution telemetry,
so a `drift` verdict is diagnosable instead of guessed at.
