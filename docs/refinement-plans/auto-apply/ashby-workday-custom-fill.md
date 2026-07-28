# Ashby / Workday / custom-site browser fill — extending Layer 2 past Greenhouse+Lever

*See [`../README.md`](../README.md) for how this plan relates to the others.*

**Status (2026-07-21): not started, not queued.** Written down after a user question during
review of the Step 10 gap #1 fix ("will it open a browser and pre-fill Ashby/Workday/a company's
own careers page?") made explicit that today's answer is no, and that this is a deliberate
current boundary rather than a bug. This doc exists so the boundary and the options for moving it
are on record for a later look, not because work is scheduled.

## Current behavior (as shipped, Phases 1–2)

`FILLABLE_CHANNELS = {"greenhouse", "lever"}` (`scripts/autoapply.py:106`) is the *only* gate
Layer 2 (the Playwright pre-fill) checks. Every other channel — `ashby`, `workday`, `linkedin`,
`indeed`, `unknown` (which is what a company's own custom careers domain, e.g. Netflix's, routes
to) — still gets full Layer 1 treatment (route detection, field resolution, Notion write, HTML
answer sheet), it just never gets a browser opened. `run.py --stage 7 --fill` logs `"○ No
browser fill for '{channel}' — apply from the answer sheet by hand."` and moves on.

This is not one uniform gap:

- **LinkedIn / Indeed are excluded *by rule*, permanently.** Not a target for this plan.
  Automating either violates ToS and is behaviorally detected — one comparable open-source
  auto-applier reportedly had its bot click recruiter *message* buttons mid-conversation.
  `docs/backlog/step-10-auto-apply-subsystem.md` §4 already calls this "Manual only" for both.
- **Ashby has no public per-job schema fetch today.** Falls back to `GENERIC_QUESTIONS`
  (`schema_known=False`), same as any unrecognized channel. §4 of the backlog doc rates it
  "Partial" schema read and flags Turnstile/captcha as common — a browser adapter here would
  need to handle a lot of unknowns sight-unseen.
- **Workday is explicitly "Phase 4, not started"** per `docs/TODO.md` — a separate tenant per
  company, ~30% resume-parser failure rate reported in the research behind this subsystem's
  design (`docs/backlog/step-10-auto-apply-subsystem.md` §4/§11). Account provisioning per
  company is the real cost, not selector work.
- **A custom company careers page (`unknown` channel)** has no schema at all — arbitrary form,
  arbitrary fields, no way to know ahead of time whether Layer 1 even resolved the right things.

## Trigger criteria — when to actually pick this up

Watch for one of these before spending implementation time (mirrors the pattern in
[`../sourcing/career-site-enrichment-fallback.md`](../sourcing/career-site-enrichment-fallback.md)):

- The tracker accumulates enough real Ashby/Workday/custom-domain `Resume Tailored` rows that
  hand-typing the answer sheet becomes the actual bottleneck in daily use (today the tracker
  holds effectively zero non-Greenhouse ATS rows at volume — see `docs/TODO.md` Step 10's note
  that 413 LinkedIn / 90 Indeed / 4 unknown of 508 total, meaning `ENABLED_SOURCES` weighting
  toward ATS boards is itself a prerequisite this hasn't hit yet).
- Ashby specifically: a live schema-read attempt is worth trying cheaply first (see Option A) —
  if Ashby's public postings JSON turns out to expose a `?questions=true`-equivalent the way
  Greenhouse's does, most of the Layer-1 groundwork from gap #1 (label-based `_LABEL_RULES`
  resolution) already carries over with no planner changes.

## Options considered

| Option | What it buys | Cost |
|---|---|---|
| **A. Ashby schema-driven fill** — probe Ashby's public job-posting API for a fuller field schema (same idea as Greenhouse's `?questions=true`); if one exists, add an `ashby` adapter to `FILLABLE_CHANNELS` reusing the existing `_resolve_field`/`build_application_plan` machinery. | Extends the cheapest, most deterministic substrate (schema-driven browser fill) to a second real ATS. Directly reuses gap #1's `_LABEL_RULES` address work. | Small-to-medium if the schema exists; needs a spike first since it's unconfirmed (§4 rates Ashby's schema read only "Partial" today) — the spike itself is the first real cost. |
| **B. Agentic browser driver for Workday/custom sites** — per `docs/backlog/step-10-auto-apply-subsystem.md` §5, use a computer-use/Claude-in-Chrome-style agent instead of schema-driven Playwright selectors: it self-locates fields, handles novel/multi-page forms, and pauses for the human on captcha/auth. | The only realistic path for the long tail (Workday's per-tenant UI, arbitrary custom sites) — survives selector drift instead of being brittle to it. | Real: slower, costs model calls per application, and Workday specifically still needs per-company account provisioning regardless of driver quality — that's a cost this option doesn't remove. |
| **C. Leave as-is; improve the answer sheet instead.** No browser adapter work; invest instead in making the Layer-1 answer sheet faster to hand-apply from (e.g. one-click copy per field, a browser extension, or just better formatting). | Cheapest option available; matches the "answer sheet only, forever" posture already locked in for LinkedIn/Indeed, extended pragmatically to the others until real volume justifies more. | Doesn't reduce apply time the way a real fill would — it's a smaller win, but zero new risk (no new selectors, no new captcha handling, no new per-company accounts). |

> **Update (2026-07-26): Option C has its own plan now** —
> [`browser-extension-prefill.md`](browser-extension-prefill.md) works the "browser extension"
> half of Option C out in full, and argues it is not merely the cheap consolation option assumed
> above but a *better substrate* than A or B: an extension reads the live DOM inside your
> already-authenticated session, which removes the per-ATS schema probe Option A depends on, the
> per-page model cost of Option B, and Workday's per-tenant account provisioning entirely. The
> sequencing below is written as if a Playwright adapter is the path; weigh it against that doc
> before acting on it. Whichever of the two ships, the other doc gets deleted in the same change.

## Recommended sequencing (when triggered)

1. **Confirm the trigger first** — don't build ahead of real Ashby/Workday/custom volume in the
   tracker; gap #1's address/attachment fix already over-delivered once at explicit user request
   (see `docs/refinement-plans/sourcing/career-site-enrichment-fallback.md`'s B/D precedent) and
   that pattern shouldn't repeat here without a concrete need.
2. **A (Ashby spike) before B (agentic Workday/custom)** if/when triggered — much cheaper to
   validate, and a confirmed public schema would mean most of the Layer-1 plumbing (label rules,
   attachment dedupe from gap #1) needs no rework at all, only a new adapter registration.
3. **B only for Workday/custom** — and only once Phase 3 (deliberate submit) has been revisited
   per `docs/TODO.md`, since an agentic driver that can locate and fill arbitrary fields is a
   meaningfully bigger trust surface than the current deterministic schema-driven fill; the
   existing "never submits" guarantee needs to hold just as hard for an agentic path as it does
   for the schema-driven one today.

## Files (when implemented)

- **Modify:** `scripts/autoapply.py` — `FILLABLE_CHANNELS`, a new `ashby` (or others) entry;
  `_CHANNEL_DOMAINS`/`detect_apply_channel` already route correctly, no change needed there.
- **New (Option A):** an Ashby-schema fetch helper mirroring the Greenhouse `?questions=true`
  fetch already in this module, gated the same way (never raises, degrades to
  `GENERIC_QUESTIONS`/`schema_known=False` on failure).
- **New (Option B):** a separate agentic-driver module, kept out of `autoapply_browser.py` the
  same way Layer 2 is kept isolated from Layer 1 today — so a flaky agentic path can't take down
  the deterministic Greenhouse/Lever fill.

## Verification (when implemented)

1. **A:** confirm a real Ashby job's schema fetch returns field-level data (not just posting
   metadata); run the existing `tests/test_autoapply_plan.py` address/attachment cases against
   it unchanged to confirm the Layer-1 resolution logic needs no adjustment.
2. **B:** exercise against one real Workday job and one real custom careers page in `--dry-run`
   first (per the existing sampling contract — zero Notion writes, `--limit` to control blast
   radius) before ever running live; confirm the "never submits" guarantee holds under an
   agentic driver the same way `tests/test_autoapply_notion.py` asserts it for the current
   Playwright-based Layer 2.
