# Step 15c — Side-panel shell + read-only extension overlay (Layer 3, increment 2)

**Status:** queued, not started (2026-07-31). Size **S**. Depends on
[step-15b](step-15b-plan-endpoint-identify-job.md). Third of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first). Blocks [step-15d](step-15d-resume-attach.md) and
[step-15h](step-15h-job-list-launcher.md) (needs the panel shell to render a job list into).
Retitled/rescoped 2026-07-31 from "popup + on-page badge overlay" to "side-panel shell" when
`step-15-interactive-launcher.md` was folded in — the primary surface is now a docked
`chrome.sidePanel` page instead of a click-to-open popup; the badge overlay logic is unchanged.

## Goal

The first browser-visible artifact: an unpacked MV3 extension that scrapes the page, calls
`/plan`, and **shows** the result — badges per field, a docked side panel with job match + resume
filename + a Copy-path button. It writes nothing to any form yet. This alone already beats the
static HTML answer sheet, and works on every site including LinkedIn/Indeed (as a read-only
overlay).

## Scope

**In:** `manifest.json` (incl. `"side_panel"` permission), `background.js` (service-worker fetch,
holds the token — see epic's "Fetch location" decision; also owns `sidePanel.setOptions`),
`content.js` (DOM scrape → schema, badge overlay, **no fill code yet**), `overlay.css`,
`panel.html`/`panel.js` (the docked side panel — supersedes a standalone `popup.*` as the primary
surface), `options.*` (token/port config).

**Out:** any field fill (`step-15e`), any file attach (`step-15d`), drafts (`step-15f`), the
confirm-applied button (`step-15g`), the job list / extension-initiated navigation (`step-15h`,
which renders *into* this panel shell but is a separate story), multi-session state (`step-15i`).

## Implementation

- Content script scrapes the live form into the schema `_dom_to_schema()` (`step-15b`) expects,
  POSTs to `/plan`, and renders the response as badges next to each question (`ready` /
  `review_required` / read-only) — display only.
- Side panel (`panel.html`/`panel.js`, docked via `chrome.sidePanel` in the same window as the
  tab) shows: matched job title/company (or the rung-3 candidate list to pick from when
  `identify_job()` returns ambiguous), the resume filename from `/resume/meta`, and a **Copy path**
  button using the `abs_path` field — no file bytes cross the wire in this story.
- Distribution: unpacked/developer-mode only (epic decision — a store listing for something that
  reads application forms is a different review problem; don't second-guess this here).
- Token: read from options page, sent as an auth header from the background service worker only —
  never let it reach `content.js`, `panel.js`, or the page's own DOM/JS context.
- LinkedIn/Indeed: render the same read-only badges the bridge already returns
  (`_READONLY_CHANNELS`, `step-15b`) — no special-casing needed in JS, since the server already
  rewrote those fields to `review_required` with a `channel read-only` source string. This is the
  proof point that enforcement lives server-side, not in this file.

## Files

**New:** `extension/manifest.json`, `extension/background.js`, `extension/content.js`,
`extension/overlay.css`, `extension/panel.html`, `extension/panel.js`, `extension/options.html`,
`extension/options.js`.
**Modified:** `tests/test_autoapply_notion.py` — start parametrizing the existing
`test_source_has_no_submit_click`-style grep (`:66`) over `content.js` (and, once it exists,
`panel.js`) too, asserting it contains no submit-token, no `confirm-applied`, no `applied`, no
`draft` reference yet (these tokens start meaning something only in `step-15d`/`f`/`g`; asserting
their absence now catches scope creep early).

## Verification

Automated (Python-side, no browser needed): none new beyond what `step-15a`/`b` already cover —
this story is genuinely JS-only apart from the grep addition above.

**Live** (manual, on forms you do not intend to submit):
1. Load unpacked extension, open a live Greenhouse job. Badges match the plan `/plan` would return
   for the same DOM via `curl`.
2. Side panel names the right role and the right `.docx` filename; re-open the same job via
   `?gh_src=test` and via the `job-boards.` host — both still identify the same job (proves
   `step-15b`'s normalization is exercised end-to-end, not just in unit tests).
3. Open an untracked job (no Notion match): panel shows "no match", resume badge shows
   `resume-missing`, no filename/path offered.
4. LinkedIn Easy Apply and an Indeed apply page: every field badged `review_required`
   read-only, no fill affordance shown at all, filename + Copy path still work.
5. Nothing on the page is modified — DevTools shows no value written into any input.

## Risks

Token handling is the one thing this story can get wrong with real consequences: confirm via
DevTools that the auth header never appears in a request initiated from `content.js`'s own
execution context, only from `background.js`.
