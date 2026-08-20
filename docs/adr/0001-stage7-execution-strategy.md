# ADR 0001 — Stage 7 (auto-apply) execution strategy: four unreconciled directions

**Status:** proposed / undecided at the `spec/` level — this is a blocker record, not a
recommendation. Nothing in this document picks a winner. Note the asymmetry below: one of the four
directions already has a series of **closed** decisions recorded on GitHub that `spec/` never
absorbed; this ADR's job is to surface that gap, not to relitigate those closed decisions.

## Why this exists

Stage 7 currently has **four** separate designs for the same problem (getting a planned
application actually filled and, in some designs, submitted), tracked in two different systems
that don't talk to each other — `spec/` folders and a GitHub-issue "wayfinder" decision chain —
and nothing in the repo reconciles them. Four issues are still open on exactly this question:

- [#24](https://github.com/Iamkach/careerpilot-ai/issues/24) — "Wayfinder map: Claude-in-Chrome
  auto-apply execution vs. the prefill extension" (the map issue itself, left open as an index)
- [#33](https://github.com/Iamkach/careerpilot-ai/issues/33) — testing strategy for the
  Claude-in-Chrome fill flow
- [#34](https://github.com/Iamkach/careerpilot-ai/issues/34) — whether to decommission the MV3
  extension now or keep it dormant as a rollback fallback
- [#36](https://github.com/Iamkach/careerpilot-ai/issues/36) — the human-initiated
  LinkedIn/Indeed → ATS-board redirect handoff, additive to whichever execution path wins

## The four directions

| | Layer 2 — Playwright fill | Layer 3 — MV3 browser extension | Layer 4a — Claude-in-Chrome fill | Layer 4b — self-hosted agentic submit |
|---|---|---|---|---|
| Tracked in | `spec/auto-apply-subsystem/` | `spec/application-prefill-extension/` | **GitHub issues only** — #24-#32 ("wayfinder"), `docs/research/claude-in-chrome-execution-mechanics.md`. No `spec/` folder exists for this. | `spec/auto-apply-agentic-submit/` |
| State | Shipped (Phases 1-2), fill-and-stop, still referenced as continuing in #28 | Code-complete on `main` for 8/10 increments (drafts.js + native-messaging host still stranded on an unmerged branch — see `application-prefill-extension/meta.md`), never live-verified | **Confirmed as destination 2026-08-05 (#27), replacing the extension outright** — 6 of 7 design questions closed (#26, #27, #28, #29, #30, #32); #33 (testing strategy) and #34 (decommission timing) still open | Fully designed (`spec/`'s 8-file structure complete), not started, `meta.md` was until this ADR marked `finalized` — read as decided, wasn't cross-checked against the above |
| Mode | Headless/interactive Playwright, human clicks Submit | Human-driven Chrome side panel, human clicks Fill then Submit | **This session's own `mcp__claude-in-chrome__*` tools**, sequential, human-supervised, triggered via a not-yet-built `/apply-live`-style skill (#30); a `PreToolUse` hook hard-blocks Submit by default (#28) | Self-hosted, MCP-style agentic loop, **clicks Submit autonomously** (no default block) |
| Reach | `FILLABLE_CHANNELS = {greenhouse, lever}` only | Any site the human has open + logged into | Any site the human has open + logged into (extension's reach, minus the extension's reliability problems) | Whatever the agentic loop can navigate |
| Written when | Earliest | 2026-07-30–08-01 | 2026-08-05–07 (decisions), research dated same window | 2026-08-10 (references `docs/research/agent-browser-landscape.md`, same date) — **after** the Layer 4a decisions, but its `problem.md` never mentions them |

## Where they conflict

- **Layer 4a supersedes Layer 3 by an already-closed decision** (#27: "extension path ruled dead
  — not worth debugging back to reliable"), but `spec/application-prefill-extension/meta.md`
  still reads `in-progress` with no mention of this. #34 is the only genuinely open piece of that
  transition (decommission now vs. keep dormant).
- **Layer 4a and Layer 4b were designed for the same problem two sessions apart, apparently without
  cross-reference.** Layer 4a's wayfinder chain went through seven separate closed decisions —
  disqualifying-field enforcement (#26), no-auto-submit hard-block via `PreToolUse` hook (#28),
  failure-mode handling (#29), orchestration/trigger shape (#30) — that Layer 4b's `spec/` folder
  does not reference or reconcile with. It is not yet established whether Layer 4b is a genuine
  alternative to Layer 4a, a redundant re-derivation of it, or a next step *after* it — that
  determination is left to the user, not made here.
- **Layer 2 is not explicitly superseded by anything** — #28 applies the same `PreToolUse`
  no-auto-submit hook "uniformly to Claude-in-Chrome and Layer 2," implying Layer 2 keeps running
  in parallel rather than being replaced. Whether that's still the intent given Layer 4a's broader
  reach is unaddressed.
- **Follow-on doc debt already flagged inside the wayfinder chain itself, not yet done:** #28 and
  #29 both call out required `CLAUDE.md` updates (the "no submit code path… not behind a flag"
  claim for Layer 2 no longer holds once the shared `PreToolUse` hook lands; the Stage 7 "never
  guessed" language needs narrowing to what `_LABEL_RULES` structurally catches). Neither has
  been applied to `CLAUDE.md` as of this ADR.

## What's NOT in question

Whatever combination of directions wins, the standing invariant across every version of Stage 7 to
date is untouched by this ADR: eligibility/sponsorship/salary answers come only from
`APPLICATION_PROFILE`/`EEO_RESPONSES`, never AI-composed, never guessed. Both Layer 4a (#26) and
Layer 4b's own `problem.md` independently affirm this as non-negotiable. This ADR does not reopen
that, and neither closed wayfinder decision claims to.

## Decision

**Not made yet at the `spec/` level.** Recorded here so the next person to touch Stage 7 sees all
four directions — including the one that already has closed decisions living only in GitHub issues
— before picking up any one spec in isolation. At minimum, before further Stage 7 work: (1)
reconcile whether Layer 4b is meant to supersede, extend, or duplicate Layer 4a's already-decided
shape, and (2) resolve #33/#34/#36.
