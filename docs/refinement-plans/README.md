# Refinement Plans — index

## Scope: refinement-plans vs. backlog

This directory holds a plan **while it's still at idea/discussion level** — the design isn't
finalized, or it's finalized but deliberately not queued yet (see "trigger criteria" on each plan
below). [`../backlog/`](../backlog/) holds a story **once it's finalized and lined up to be
implemented**.

A plan moves in exactly one direction: refinement-plans → backlog. When a plan is finalized and
queued, its content is folded into a new (or existing) `docs/backlog/step-N-*.md` story — the
"why" sections (sources considered/rejected, binding decisions, risks) condensed alongside the
implementation checklist — and the refinement-plan doc is **deleted**, not left as a duplicate
"full spec" the backlog story points back to. One doc per story once it's queued, not two. See
[`../backlog/README.md`](../backlog/README.md) for the reverse direction of this rule.

---

Originally six plan documents proposed changes to the AI job-search pipeline. Five are fully
implemented and retired; their content is summarized in [`../CHANGELOG.md`](../CHANGELOG.md):

- **Sourcing spike** (`sourcing/scraping-sources.md`) — resolved by the `valig`/`misceres`
  actor swap. Deleted.
- **Multi-source sourcing** (`sourcing/multi-source-sourcing.md`) — implemented as
  `scripts/sources.py`. Deleted.
- **Stage-1 filtering rework** (`filtering/stage1-filtering-rework.md`) — AI `company_type`
  classification, `Sponsorship`/`Retry` status handling, all landed as Step 5. Deleted.
- **Hybrid agentic migration** (`reliability/hybrid-agentic-migration-plan.md`) — reliability
  half (retries, typed errors, `Retry` status, kill fabricated `score=50`) landed as Step 5;
  the `AI_ROUTING`/tiering half was superseded by the shipped `FAST_PROVIDER`/`QUALITY_PROVIDER`
  design. Deleted.
- **Runtime `--ai-mode` flag** (`ai-provider/runtime-ai-mode-flag.md`) — landed as Step 8, plus
  an added `--metered-provider` flag and a new `openrouter` provider beyond the original spec.
  Deleted.

Two more plans were finalized and queued (Step 7, Step 11) — folded into their backlog stories
and deleted:

- **Communications subsystem** (`communications/communications-subsystem.md`) — finalized,
  content merged into [`../backlog/step-7-communications-subsystem.md`](../backlog/step-7-communications-subsystem.md).
  Deleted.
- **Forkable setup** (`onboarding/forkable-setup.md`) — finalized, content merged into
  [`../backlog/step-11-forkable-setup.md`](../backlog/step-11-forkable-setup.md). Deleted.

Three plans remain here because they are **not yet finalized/queued** — still idea-level or
deliberately deferred pending a trigger:

| Plan | Status | Covers |
|---|---|---|
| [`sourcing/career-site-enrichment-fallback.md`](sourcing/career-site-enrichment-fallback.md) | deferred — not queued, see trigger criteria | `generic_url_fetch()` gaps: no structured fields, JS-rendered SPAs return near-empty, no retry ceiling |
| [`auto-apply/ashby-workday-custom-fill.md`](auto-apply/ashby-workday-custom-fill.md) | deferred — not queued, see trigger criteria | Stage 7 Layer 2 browser fill only covers Greenhouse/Lever; Ashby/Workday/custom careers sites get an answer sheet only |
| [`auto-apply/browser-extension-prefill.md`](auto-apply/browser-extension-prefill.md) | deferred — not queued, design settled | A browser extension + localhost bridge as a Layer 3 pre-fill: reads the live DOM, so it covers Ashby/Workday/custom with no per-ATS schema or selector work |
| [`tracking/inbound-email-status-sync.md`](tracking/inbound-email-status-sync.md) | idea-level, not queued | Read Gmail replies from applied companies, match to a tracker row, classify (rejection/interview/OA/offer), and update Notion `Status` under a narrow, auditable confidence gate |

The two `auto-apply/` plans address the **same bottleneck** (hand-typing the answer sheet for
non-Greenhouse/Lever forms) with different substrates, and are deliberately kept as two docs while
both are unqueued — neither supersedes the other yet. If the extension plan is the one that ships,
`ashby-workday-custom-fill.md` should be deleted as part of that same change (its Options A/B
become moot and its Option C *is* the extension); if instead a Playwright adapter is chosen, the
reverse applies.

**Both were re-triggered on a measurement, and both stay parked (measured 2026-07-29).** Their
original triggers counted the *posting* host (413 LinkedIn / 90 Indeed of 508), but fillability is
decided by the *apply-form* host. A throwaway spike measured the difference, including a live Apify
probe of both keyword actors, and returned three things:

- **LinkedIn yields no apply destination at all** — the actor populates no apply-URL field (0/20
  across five candidate names, making `sources.py:186`'s `applyUrl` fallback dead code), and the
  unauthenticated job page carries none either. Unobtainable, at scrape time or after.
- **Indeed exposes one on ~20% of listings**, and only with `followApplyRedirects: True` (off, all
  populated values are `indeed.com` wrappers). The flag costs ~+64% wall-clock.
- **Every reachable destination was a custom career site, not an ATS** — zero Greenhouse/Lever/
  Ashby/Workday.

So neither plan is triggered, and the binding constraint is upstream of both: because the two
dominant sources structurally cannot produce a fillable apply URL, weighting `ENABLED_SOURCES`
toward Greenhouse/Lever/Ashby is the **only** mechanism that puts one in the tracker. Each plan
carries the full numbers and what they imply for its own substrate. The spike was deleted per its
own contract once transcribed.

When either hits its trigger criteria and gets prioritized, fold it into a new
`docs/backlog/step-N-*.md` story and delete it from here, following the pattern above.
