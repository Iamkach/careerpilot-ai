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

**Corrected 2026-07-29 — the old trigger measured the wrong host.** It counted Ashby/Workday/
custom-domain rows by the tracker's **posting** host (413 LinkedIn / 90 Indeed / 4 unknown /
1 Greenhouse of 508). Fillability is decided by the **apply-form** host, which is routinely
different: `plan_for_job()` routes off `detect_apply_channel(job["url"])` with no redirect
resolution anywhere in Layer 1 (backlog §3 scenario #8, designed and never implemented), and
`scripts/sources.py` discards a real destination on the Indeed path — `scrape_indeed()` puts
`externalApplyLink` third behind `job["url"]` and sets `followApplyRedirects: False`. So a
LinkedIn-sourced row applying on a company's Greenhouse form counts against *this* plan today when
Layer 2 could already fill it — that was the hypothesis. It was then measured; see below.

### Measured 2026-07-29 (`scripts/spike_apply_redirect.py`, since deleted)

A throwaway spike measured the resolved apply host, including a live Apify probe of both keyword
actors (20 fresh listings each). Full numbers and the per-field table live in
[`browser-extension-prefill.md`](browser-extension-prefill.md); the three results that bear on
*this* plan:

1. **LinkedIn cannot yield an apply destination at all** — the actor populates no apply-URL field
   (0/20 across five candidate names, so `sources.py:186`'s `applyUrl` fallback is dead code), and
   an unauthenticated fetch of a LinkedIn job page returns a guest/captcha shell with none either.
   Structurally unobtainable, at scrape time or after.
2. **Indeed exposes an external apply link on only ~20% of listings**, and only when
   `followApplyRedirects: True` (off, all populated values are `indeed.com` wrappers). The flag
   costs ~+64% wall-clock (33.0s → 54.1s / 20 items) against `_apify_run()`'s 400s poll budget —
   and that helper raises rather than returning a partial dataset, so flipping it without raising
   the poll count would turn a slow scrape into a silently empty one.
3. **Every reachable destination was a custom career site, not an ATS** — `careers.cisco.com`,
   `careers.baptisthealth.net`, `careers.massmutual.com` (Phenom-style, classified `unknown`).
   **Zero** Greenhouse, Lever, Ashby, or Workday.

**Consequence for this plan: result 3 argues against it specifically.** An Ashby adapter (Option A)
and a Workday driver (Option B) are both bets that Ashby/Workday rows will accumulate. The measured
reality is that the pipeline's dominant sources produce *custom career sites* when they produce
anything fillable at all — which is the case
[`browser-extension-prefill.md`](browser-extension-prefill.md) handles and per-ATS adapters
structurally cannot. Nothing in the measurement supports building an Ashby or Workday adapter next.

**Prerequisite before either option is worth revisiting.** LinkedIn yields no apply URL and Indeed
yields ~20% custom sites, so shifting `ENABLED_SOURCES` weight toward Greenhouse/Lever/Ashby is the
**only** mechanism that puts real ATS apply URLs in the tracker — those sources hand over the ATS
URL directly. Do that, then re-measure. Only if Ashby rows specifically accumulate does Option A's
cheap schema spike become worthwhile: if Ashby's public postings JSON exposes a
`?questions=true`-equivalent the way Greenhouse's does, most of the Layer-1 groundwork from gap #1
(label-based `_LABEL_RULES` resolution) carries over with no planner changes.

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
