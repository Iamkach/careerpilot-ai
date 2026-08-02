# Step 15e — Fill text/select fields (Layer 3, increment 3b)

**Status:** queued, not started (2026-07-31). Size **S**. Depends on
[step-15d](step-15d-resume-attach.md) having passed its go/no-go. Fifth of nine sub-stories split
from [step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read
it first). Independent of [step-15f](step-15f-essay-drafts.md) and
[step-15g](step-15g-confirm-applied.md) once this lands.

## Goal

Remove the repetitive typing: fill every field the plan marked `status == "ready"` on an explicit
Fill click. Never on page load — a wrong eligibility answer is unretractable, so the human gesture
stays required for every run, not just the first.

## Scope

**In:** the fill loop in `content.js` for text inputs, selects, radios/checkboxes matching plan
entries with `status == "ready"`.

**Out:** file attach (already done, `step-15d`), essay drafts (`step-15f` — those stay
`review_required` and are structurally excluded by the same predicate this story introduces, no
special-casing needed), confirm-applied (`step-15g`).

## Implementation

- Fill predicate: `fields.filter(f => f.status === "ready")` — the same predicate shape as
  `autoapply_browser.py:155`, so Layer 2 and Layer 3 agree on what "ready" means without sharing
  code.
- Fill on click only, never on load or on plan-fetch — re-affirm this every time this file is
  touched, since it's the one behavior in this whole epic that must never regress silently.
- After filling, badge each filled field distinctly from an unfilled `review_required` one, so a
  glance at the form shows what's left to do by hand.
- LinkedIn/Indeed fields arrive pre-rewritten to `review_required` by the bridge (`step-15b`), so
  they are excluded by the same filter with no extra code in this file — this is the proof that
  read-only enforcement doesn't need duplicating client-side.

## Files

**Modified:** `extension/content.js` (fill loop only — no new server routes this story).

## Verification

**Live, on forms you do not intend to submit:**
1. Click Fill on a Greenhouse form with a resolved plan: every `ready` field is filled with the
   value the CLI (`python scripts/autoapply.py --url <job>`) would have produced for the same job.
2. Nothing is filled before the click — reload the page, badges show, no input has a value yet.
3. LinkedIn/Indeed: Fill button is absent or is a no-op; no field receives a value.
4. **Submit stays untouched** — DevTools Network shows no POST leaving the page until *you* click
   the form's own Submit button. This is a regression check that belongs to every story touching
   `content.js`, not just this one, but is most directly at risk here since this is the first story
   that writes into the form at all.
5. A `review_required` field (including a drafted-but-not-inserted essay, once `step-15f` exists)
   is never filled by the Fill button.

## Risks

Same `isTrusted: false` caveat as `step-15d` — a synthetic `input`/`change` event may not satisfy
every framework's validation state (e.g. a React-controlled input that only trusts its own
`onChange`). Where this happens, the field stays visibly unfilled rather than silently wrong;
there's no autofill-without-verification path in this story.
