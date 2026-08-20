# Auto-Apply subsystem (Stage 7)

**Status:** in-progress — Phases 1-2 (read + plan, and semi-auto Greenhouse/Lever browser fill,
never submitting) landed 2026-07-19 and are documented here as shipped background. Phase 3
(deliberate submit) is deferred by choice pending real-world use of the fill path. Phase 4
(agentic long tail — Workday/custom) is largely superseded by `spec/application-prefill-extension/`
for the interactive case; the Playwright/agentic route was never started and stays open only for
the parts an interactive extension can't reach (unattended runs).
**Priority:** P2 — high user value, but the highest *execution risk* in the roadmap (anti-bot,
ToS, per-site fragility). Ship the safe slice first.
**Size:** L-XL, but *phaseable* — a genuinely useful semi-auto slice is S-M.
**Depends-on:** [] — depends on Stage 2 (tailored `.docx` per job), the Notion status pipeline,
and `scripts/sources.py` (the `source`/URL-domain routing key this reuses); none of those are yet
migrated into `spec/`.

Sections 1-8 below (problem.md, constraints.md, plan.md) are the original design analysis, kept
as rationale for what shipped and what's still open. Section 11 of the original doc ("What shipped,
and what the research changed") is folded into problem.md's background and plan.md's "Landed"
record.
