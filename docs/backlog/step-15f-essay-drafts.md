# Step 15f — Interactive draft panel + `POST /drafts` (Layer 3, increment 4)

**Status:** queued, not started (2026-07-31). Size **S/M**. Depends on
[step-15b](step-15b-plan-endpoint-identify-job.md) (needs `/plan` + `identify_job()`) and
[step-15c](step-15c-extension-readonly-overlay.md) (needs the side-panel shell to render into).
Independent of [step-15d](step-15d-resume-attach.md)/[step-15e](step-15e-field-fill.md). Sixth of
nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first). Retitled 2026-07-31 from "Draft panel" to "Interactive draft panel" when
`step-15-interactive-launcher.md` was folded in — same `POST /drafts` contract, rendered in the
docked side panel (`step-15c`) rather than a popup-adjacent panel; no implementation change.

## Goal

Remove essay retyping without ever auto-filling one: surface an AI-drafted answer per free-text
question for the human to read, edit, and insert — a separate gesture per field, never triggered by
the main Fill button.

## Scope

**In:** `POST /drafts` (one AI call per question); the draft panel in a new `drafts.js`; per-field
Insert button; re-badging after insert.

**Out:** field fill for non-essay fields (`step-15e`, independent), resume attach (`step-15d`,
independent), confirm-applied (`step-15g`).

## Implementation

### `POST /drafts` — separate route, not part of `/plan`

One AI call per question is 10–30s and would block the fill if bundled into `/plan`; drafting
should be its own gesture. Gated on `AUTOAPPLY_DRAFT_ESSAYS` (`settings.py:395`) and on
`identify_job()` having matched (drafting needs the JD + resume text — no match means no draft,
and the field stays plain `review_required`).

### Enforcement is structural, not special-cased

The fill loop (`step-15e`) iterates `fields.filter(f => f.status === "ready")` — a drafted field is
`review_required`, so it is excluded by the *same* predicate that already excludes it. **Add no
`draft` branch to the fill path** — if a future change needs one, that's a sign drafting logic is
leaking into the fill file.

### File separation makes that greppable

Fill loop lives in `content.js`; the entire draft panel and per-field Insert live in `drafts.js`.
Assert `draft` never appears in `content.js` — extend the grep test `step-15c` started.

### Insert semantics

Insert is a separate gesture per field, never triggered by the main Fill button. After insert,
re-badge *"inserted — edit before submitting"* — never claim the field is done; the human still
edits and submits by hand.

## Reused verbatim

`draft_free_text_answers()` `autoapply.py:607` (already leaves `status`/`value` untouched at
`:642`) · `_resume_text_for()` `:647`.

## Files

**New:** `extension/drafts.js`.
**Modified:** `scripts/autoapply_server.py` (`handle_drafts`) · `tests/test_autoapply_server.py`
(adds `/drafts` cases) · `tests/test_autoapply_notion.py` (extend the `content.js` grep to assert
no `draft` token).

**Conftest gotcha:** drafting calls into `scripts.autoapply`, whose `ai_chat` is bound at import
(`conftest.py:11-17`) — patch `patch_ai_chat(autoapply)`, not `(autoapply_server)`, or the test will
silently hit a real (or unmocked) AI call path.

## Verification

Automated:
1. Drafted field is never `ready` after `/drafts` runs — status/value are untouched, only a
   `draft` key is added.
2. Drafts require a matched `page_id`; an unmatched job's free-text fields get no draft key at all.
3. `content.js` contains no `draft` token (grep, extended from `step-15c`).
4. `AUTOAPPLY_DRAFT_ESSAYS=False` → `/drafts` is a no-op (or 404/disabled response), matching the
   existing stage 2/7 pattern of a settings-gated feature degrading cleanly.

**Live:**
5. Draft panel shows one AI-drafted answer per free-text question on a matched job; editing the
   text before Insert is possible; Insert writes exactly that (possibly edited) text into the
   field and re-badges it, without touching any other field.
6. Unmatched job: no draft panel content, fields stay `review_required` with no draft affordance.

## Risks

None new beyond the epic's general "second UI surface, no JS test runner" maintenance risk — keep
`drafts.js` thin and let the grep + Python contract tests carry the weight.
