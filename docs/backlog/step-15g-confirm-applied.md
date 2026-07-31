# Step 15g — `POST /confirm-applied` + panel button (Layer 3, increment 5)

**Status:** queued, not started (2026-07-31). Size **S**. Depends on
[step-15b](step-15b-plan-endpoint-identify-job.md) (needs `identify_job()` to resolve a `page_id`)
and [step-15c](step-15c-extension-readonly-overlay.md) (needs the side panel to put a button in).
Independent of [step-15d](step-15d-resume-attach.md)/[step-15e](step-15e-field-fill.md)/
[step-15f](step-15f-essay-drafts.md). Seventh of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first — this story carries the epic's `Applied`-invariant reformulation and is the highest-stakes
increment in the project). Container renamed 2026-07-31 (`popup.js` → `panel.js`) when `step-15c`
was rescoped to a docked side panel — no change to this story's logic or controls.

## Goal

Remove the Notion round-trip after a real submit: one explicit button in the side panel that
records `Applied` in Notion, with an audit trail proving the claim came from a human click, not
from planning or fill code.

## Scope

**In:** `POST /confirm-applied`; `HUMAN_CONFIRMED_STATUS` / `CONFIRMABLE_STATUSES` constants; the
panel confirm button; the disjointness test against `WRITABLE_STATUSES`.

**Out:** everything else — this route has no dependency on resume attach, field fill, or drafts
being present, and should not gain one.

## Implementation — the `Applied` invariant, reformulated not broken

`WRITABLE_STATUSES` excludes `Applied` (`autoapply.py:65-80`), asserted by
`tests/test_autoapply_notion.py:50-63`. The rationale (`:67-71`) is that comparable tools mark jobs
applied that were never submitted — inference from an unobservable event. That comment already
names the permitted case: "set by the human, by hand, after they click Submit." It only assumed
that hand was in Notion's UI; this story gives it a second hand, gated identically hard.

**What genuinely weakens:** today the guarantee is *physical* — no code path exists at all. After
this story, one process holds both a credential and a path to the write. The threat model shifts
from "the tool lies" to "a bug or a future refactor reaches the write without a human keystroke."
Every control below ships in this story, not later:

| # | Control |
|---|---|
| 1 | `WRITABLE_STATUSES` stays byte-identical. New `HUMAN_CONFIRMED_STATUS` / `CONFIRMABLE_STATUSES` live in `autoapply_server.py`; a test asserts the sets are disjoint |
| 2 | Route is **`POST /confirm-applied`**, not a generic `POST /status`. The status literal is hard-coded in the handler body and the route **accepts no status field** — no data path from a computed value to the write |
| 3 | Body requires `confirmed_by == "human"`, else 400 |
| 4 | `page_id` (string) only; a list is explicitly rejected. "Mark the backlog applied" is structurally never one call away |
| 5 | The confirm button lives in `panel.js`. `content.js` must contain no reference to `confirm-applied` or `applied` — enforced by extending the grep test `step-15c`/`step-15f` already carry forward |
| 6 | Write via `db_update_status_verified()` (`utils.py:876`), setting `Date Applied` and `Application Log = "<date> Applied — human-confirmed via extension"`. Every tool-mediated `Applied` is labelled and auditable — this is what replaces the lost "cannot happen" proof |

Existing tests are kept verbatim (both still true, and now more load-bearing);
`test_source_has_no_submit_click` (`:66`) is *parametrized* over more files rather than replaced.
No Notion schema change needed — `Applied` is already a status.

## Reused verbatim

`db_update_status_verified()` `utils.py:876`.

## Files

**New:** `tests/test_autoapply_applied_confirmation.py`.
**Modified:** `scripts/autoapply_server.py` (`handle_confirm_applied`, `HUMAN_CONFIRMED_STATUS`,
`CONFIRMABLE_STATUSES`) · `extension/panel.js` (confirm button) ·
`tests/test_autoapply_notion.py` (final parametrization pass over the submit/applied/draft grep,
now covering `panel.js` too) · `CLAUDE.md` (this is also the natural point to land the epic's
remaining doc close-out — see below).

## Verification

Automated:
1. `HUMAN_CONFIRMED_STATUS` / `CONFIRMABLE_STATUSES` disjoint from `WRITABLE_STATUSES` (test
   asserts the set intersection is empty).
2. Missing `confirmed_by` → 400, no write attempted (mock Notion, assert zero calls).
3. Happy path: sets `Applied` + `Date Applied` on exactly one page, `Application Log` contains
   `human-confirmed via extension`.
4. Batch payload (list of `page_id`s, or missing `page_id`) → rejected, no write.
5. Notion-dropped status (the DB is missing the `Applied` option, or silently ignores the write) is
   reported as a failure via `db.known_statuses`, mirroring the pattern at
   `test_autoapply_notion.py:84` — never silently "succeeds."
6. `content.js` contains no `confirm-applied` or `applied` token (grep, extended).

**Live:**
7. Confirm button on a job you actually submitted → Notion shows `Applied`, `Date Applied`, and an
   `Application Log` line containing `human-confirmed via extension`.
8. Clicking Confirm on an ambiguous/unmatched job is not offered (button disabled or absent when no
   `page_id` is resolved) — you cannot confirm-applied a job the panel couldn't identify.

## Docs close-out

**Not this story** — moved to `step-15i` (the epic's final increment) when `step-15h`/`step-15i`
were added 2026-07-31. Per the epic's "Docs lifecycle" section: add a "Layer 3 — browser extension"
subsection under Stage 7 in the root `CLAUDE.md`, and reformulate the `Never Applied` paragraph
there (`:339-343`) to match the invariant restated above. Add a Step 15 entry to
`docs/CHANGELOG.md`, and a backfilled Step 10 entry if cheap (it currently has none).

## Risks

The Applied button is a habit risk, not just a code risk: it is right there and easy to click
before you have actually submitted. The audit line (control #6 above) is the mitigation; this
residual risk is accepted knowingly, not solved.
