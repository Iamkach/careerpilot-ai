# Step 15h — Job list + launcher (Layer 3, increment 6)

**Status:** queued, not started (2026-07-31). Size **S**. Depends on
[step-15b](step-15b-plan-endpoint-identify-job.md) (needs `identify_job()`'s rung 0) and
[step-15c](step-15c-extension-readonly-overlay.md) (needs the side-panel shell to render a job
list into). Independent of [step-15d](step-15d-resume-attach.md)/
[step-15e](step-15e-field-fill.md)/[step-15f](step-15f-essay-drafts.md)/
[step-15g](step-15g-confirm-applied.md). Blocks [step-15i](step-15i-multi-session-state.md).
Eighth of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first). Folded 2026-07-31 from
`docs/refinement-plans/auto-apply/step-15-interactive-launcher.md`.

## Goal

Flip the trigger direction: instead of the human navigating to a job first and the extension
guessing whose job it is, the side panel lists jobs at `Status = Resume Tailored` and the
extension opens the one the human picks — so the `page_id` is known before navigation, not
inferred after.

## Scope

**In:** `GET /jobs/ready` in `autoapply_server.py`; the side panel's job-list view; the
`background.js` click handler that opens the tab and switches that tab's panel to the plan view.

**Out:** multi-session/per-tab state tracking beyond the single tab just opened (`step-15i`); any
ATS token/board write-back (deferred to Step 13 — this story stays read-only on that front, per
the launcher plan's resolved open question); a general `POST /status` route (not adopted — see the
epic's "Docs lifecycle" entry for 2026-07-31; `step-15g`'s `/confirm-applied` remains the only
status write the extension makes).

## Implementation

### `GET /jobs/ready`

Wraps `db_get_ready_to_apply()` (`scripts/utils.py:907`), which already returns exactly the needed
query — `Status = "Resume Tailored"`, `Date Applied` empty, sorted by ATS score desc. No new Notion
query logic. Returns `{page_id, title, company, url, score, tailored_resume_link}` per row.

### Side panel job-list view

New default view when the panel has no active job for the current tab: a scrollable list of
`/jobs/ready` rows (title, company, score), refreshed on panel open. Clicking a row is the only
interaction this story adds.

### Extension-initiated navigation

`background.js`'s click handler: `chrome.tabs.create({url: job.url})` in the current window, then
`sidePanel.setOptions({tabId, path: "panel.html?page_id=" + job.page_id})` so that tab's panel
switches to the plan view. The content script loads on the new tab as usual and calls `/plan`
carrying the known `page_id` — `identify_job()`'s rung 0 (`step-15b`) short-circuits straight to
that job, no URL-matching or ask step.

## Reused verbatim

`db_get_ready_to_apply()` `utils.py:907` · `identify_job()` rung 0 (`step-15b`) ·
`POST /plan` composition (`step-15b`) — unchanged, just called with a known `page_id` instead of a
DOM-only payload.

## Files

**New:** `tests/test_autoapply_jobs_ready_endpoint.py`.
**Modified:** `scripts/autoapply_server.py` (`handle_jobs_ready`) · `extension/panel.html`/
`extension/panel.js` (job-list view) · `extension/background.js` (click handler,
`chrome.tabs.create` + `sidePanel.setOptions`) · `extension/manifest.json` (if `"tabs"` permission
isn't already present from `step-15c`).

## Verification

Automated:
1. `GET /jobs/ready` returns rows matching `db_get_ready_to_apply()`'s contract (status filter,
   empty-`Date Applied` filter, score-desc sort) — reuse/extend that function's existing test
   fixtures rather than re-deriving them.
2. `GET /jobs/ready` makes no Notion writes (read-only endpoint).

**Live:**
3. Side panel with no active tab job shows the ready-to-apply list, sorted by score.
4. Clicking a row opens that job's URL in a new tab in the same window, and the panel immediately
   shows that job's plan — no candidate-list/ask step, confirming rung 0 fired.
5. A job whose URL 404s or fails to load still leaves the panel showing the correct plan (the
   `page_id` came from the click, not from re-deriving it off the (possibly-failed) page).

## Risks

None new beyond the epic's general "second UI surface, no JS test runner" maintenance risk. The
one thing to watch: `chrome.tabs.create` opening a tab the user didn't expect (e.g. a stale
`tailored_resume_link` job that's actually already been applied to outside this tool) — mitigated
by `/jobs/ready`'s existing `Date Applied` empty filter, unchanged from `db_get_ready_to_apply()`.
