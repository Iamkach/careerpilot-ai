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

Three more plans were finalized and queued (Step 7, Step 11, Step 15) — folded into their backlog
stories and deleted:

- **Application pre-fill browser extension** (`auto-apply/browser-extension-prefill.md`) —
  finalized, content merged into
  [`../backlog/step-15-application-prefill-extension.md`](../backlog/step-15-application-prefill-extension.md).
  Deleted.

- **Communications subsystem** (`communications/communications-subsystem.md`) — finalized,
  content merged into [`../backlog/step-7-communications-subsystem.md`](../backlog/step-7-communications-subsystem.md).
  Deleted.
- **Forkable setup** (`onboarding/forkable-setup.md`) — finalized, content merged into
  [`../backlog/step-11-forkable-setup.md`](../backlog/step-11-forkable-setup.md). Deleted.

One further plan was **superseded and deleted** rather than folded:
`auto-apply/ashby-workday-custom-fill.md` (per-ATS Playwright adapters for Ashby/Workday/custom
forms). Step 15's extension covers the same bottleneck with one code path instead of an adapter
per ATS, so its Options A/B are moot and its Option C *is* the extension. Its one still-live idea —
Ashby in `FILLABLE_CHANNELS`, which matters only for *unattended* runs — is harvested into
[`../backlog/step-15-application-prefill-extension.md`](../backlog/step-15-application-prefill-extension.md)
under "Considered and dropped."

Two plans remain here because they are **not yet finalized/queued** — still idea-level or
deliberately deferred pending a trigger:

| Plan | Status | Covers |
|---|---|---|
| [`sourcing/career-site-enrichment-fallback.md`](sourcing/career-site-enrichment-fallback.md) | deferred — not queued, see trigger criteria | `generic_url_fetch()` gaps: no structured fields, JS-rendered SPAs return near-empty, no retry ceiling |
| [`tracking/inbound-email-status-sync.md`](tracking/inbound-email-status-sync.md) | idea-level, not queued | Read Gmail replies from applied companies, match to a tracker row, classify (rejection/interview/OA/offer), and update Notion `Status` under a narrow, auditable confidence gate |

Plus one **measurement record**, not a plan and not subject to the fold-and-delete rule:
[`auto-apply/sourcing-bottleneck-analysis.md`](auto-apply/sourcing-bottleneck-analysis.md). It
holds numbers that must never be re-derived (LinkedIn 0/20 apply-URL fields, `followApplyRedirects`
+64% wall-clock, authenticated-LinkedIn rejected on account-risk grounds). **Its recommendation is
superseded** — see below — but its findings stand.

### Why the two `auto-apply/` plans resolved the way they did

They addressed the **same bottleneck** (hand-typing the answer sheet for non-Greenhouse/Lever
forms) with different substrates, and were deliberately kept as two docs while both were unqueued,
on the standing arrangement that whichever shipped, the other was deleted in the same change. The
extension shipped.

**Both were parked in 2026-07-29 on a measurement, and Step 15 un-parked one of them on a scoping
correction (2026-07-30).** The 07-29 spike established that LinkedIn yields no apply destination at
all (0/20 across five candidate field names, making `sources.py:186`'s `applyUrl` fallback dead
code), that Indeed exposes one on only ~20% of listings and only with `followApplyRedirects: True`,
and that every reachable destination was a custom career site rather than an ATS. Those findings
are sound and unchanged.

**What was wrong was the denominator.** They sized an extension by *rows the pipeline can
auto-route to a fillable URL* — but an extension routes nothing. The human navigates, and it fills
whatever form is on screen, so its population is *every application opened by hand*, including the
custom career sites reached **through** a LinkedIn posting. "LinkedIn exposes no apply URL"
constrains automated routing and says nothing about a human already standing on the form. That
correction, and nothing else, is what moved the extension plan to queued.

The upstream constraint the 07-29 analysis identified still holds **for the Playwright layer**:
weighting `ENABLED_SOURCES` toward Greenhouse/Lever/Ashby remains the only mechanism that puts a
fillable apply URL in the tracker for unattended runs. The spike itself was deleted per its own
contract once transcribed.

When either hits its trigger criteria and gets prioritized, fold it into a new
`docs/backlog/step-N-*.md` story and delete it from here, following the pattern above.
