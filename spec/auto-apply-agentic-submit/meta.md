# Auto-apply agentic submit (Stage 7 Layer 4)

**Status:** blocked — pending [docs/adr/0001-stage7-execution-strategy.md](../../docs/adr/0001-stage7-execution-strategy.md)
and the live decision ticket [#45](https://github.com/Iamkach/careerpilot-ai/issues/45)
(carried forward on [triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61)):
design is complete, but whether this spec supersedes, extends, or duplicates the confirmed
Claude-in-Chrome fill flow (#24, folded into #61) is not yet determined — Layer 3 (the MV3
extension) is already decided dropped, so this reconciliation is now against Layer 4a only.
**Priority:** P1
**Size:** L
**Depends-on:** [selector-resolution-hardening]

Replaces Stage 7 Layer 2's deterministic-only Playwright pre-fill with a self-hosted, MCP-style
agentic loop that navigates, decides, fills, and adapts across a whole application end-to-end —
including clicking Submit autonomously — while keeping eligibility/sponsorship/salary answers
mechanically restricted to `APPLICATION_PROFILE`/`EEO_RESPONSES`, never AI-composed.
