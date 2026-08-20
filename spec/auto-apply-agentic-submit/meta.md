# Auto-apply agentic submit (Stage 7 Layer 4)

**Status:** blocked — pending [docs/adr/0001-stage7-execution-strategy.md](../../docs/adr/0001-stage7-execution-strategy.md)
(design is complete, but this is one of four unreconciled Stage 7 execution directions; notably,
GitHub issues #24-#32 already worked through a closely related "Claude-in-Chrome fill flow"
design in the same window this spec was written, without cross-reference in either direction —
whether this spec supersedes, extends, or duplicates that decided direction is not yet
determined)
**Priority:** P1
**Size:** L
**Depends-on:** [selector-resolution-hardening]

Replaces Stage 7 Layer 2's deterministic-only Playwright pre-fill with a self-hosted, MCP-style
agentic loop that navigates, decides, fills, and adapts across a whole application end-to-end —
including clicking Submit autonomously — while keeping eligibility/sponsorship/salary answers
mechanically restricted to `APPLICATION_PROFILE`/`EEO_RESPONSES`, never AI-composed.
