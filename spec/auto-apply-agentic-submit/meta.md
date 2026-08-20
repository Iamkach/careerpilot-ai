# Auto-apply agentic submit (Stage 7 Layer 4)

**Status:** finalized
**Priority:** P1
**Size:** L
**Depends-on:** [selector-resolution-hardening]

Replaces Stage 7 Layer 2's deterministic-only Playwright pre-fill with a self-hosted, MCP-style
agentic loop that navigates, decides, fills, and adapts across a whole application end-to-end —
including clicking Submit autonomously — while keeping eligibility/sponsorship/salary answers
mechanically restricted to `APPLICATION_PROFILE`/`EEO_RESPONSES`, never AI-composed.
