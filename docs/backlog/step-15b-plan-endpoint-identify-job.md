# Step 15b — `POST /plan` + `identify_job()` + `GET /resume/meta` (Layer 3, increment 1)

**Status:** queued, not started (2026-07-31). Size **M**. Depends on
[step-15a](step-15a-serve-bridge-scaffold.md). Second of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first). Blocks [step-15c](step-15c-extension-readonly-overlay.md) and
[step-15h](step-15h-job-list-launcher.md) (needs this story's rung 0, added 2026-07-31 when
`step-15-interactive-launcher.md` was folded in).

## Goal

Make the bridge answer "what should go in this form, and whose job is this" from a DOM payload
alone — the machine-readable planner. No browser UI yet; verify with a synthetic DOM payload and
`curl`/a test client.

## Scope

**In:** `_dom_to_schema()` (the one genuinely new piece of logic in this whole project — a pure
function, unit-diffed against `SAMPLE_QUESTIONS` at `autoapply.py:191`); `identify_job()`'s 3 rungs
plus rung 0 (known `page_id`, see below); `POST /plan`; `GET /resume/meta`; the LinkedIn/Indeed
read-only rewrite pass, enforced **in the bridge**, not in JS.

**Out:** actually fetching resume bytes (`GET /resume`, `step-15d`) — `/resume/meta` returns
filename/size/mime/path only, no file content. The extension/content script (`step-15c`).

## Implementation

### `_dom_to_schema()`

Keep it a pure function (DOM payload in, schema-shape dict out) precisely so it unit-diffs against
the existing `SAMPLE_QUESTIONS` fixture — that diff is the proof this bridge adds no answer logic
of its own.

### `identify_job()` — 3 rungs, not the originally-specced 5, plus a launcher rung 0

Candidate pool fetched once at boot and matched in-process. Pool is
`WRITABLE_STATUSES | {"Resume Tailored"}` — **not** `Resume Tailored` alone, since Stage 7's `run()`
moves rows off it (`autoapply.py:753`); a naive pool would miss exactly the jobs Stage 7 planned.

0. **Known `page_id`** (added 2026-07-31, folded from `step-15-interactive-launcher.md`) — when the
   request already carries a `page_id` because the panel's job list (`step-15h`) opened this tab
   itself via `chrome.tabs.create`, there is nothing to guess: short-circuit straight to that job,
   skipping the candidate pool and rungs 1–3 entirely. This rung only ever fires for
   launcher-opened tabs; a hand-navigated tab (bookmark, search result, LinkedIn Easy Apply
   bounce-through) carries no `page_id` and falls through to rung 1 exactly as before.
1. **Normalized URL** — drop query/fragment, strip trailing `/apply`, fold `job-boards.`→`boards.`,
   lowercase host, strip trailing slash. The workhorse. Exact-URL match is its degenerate case:
   report the higher confidence, but skip the `db_find_job_by_url()` round-trip (it returns only a
   page id, and no `db_get_job_by_page_id()` exists — rung 1 as originally specced forces a new
   helper plus a second read).
2. **Greenhouse `(board_token, job_id)`** via `parse_greenhouse_url()` — handles the `?gh_jid=` and
   `embed/job_app` shapes that normalization alone misses (`autoapply.py:147-160`).
3. **Ask** — popup lists candidates (rendered in `step-15c`; this story returns the candidate list
   over the API). With a pool near `AUTOAPPLY_DAILY_CAP`, a 2-second click.

**Cut for v1: fingerprint matching.** It is the only rung that can produce a *wrong* match, needs
new page-side JSON-LD/`og:title` scraping, and its value comes from a stale backlog — explicitly
out of scope. Keep the *rule*: ≥2 matches → fall through to ask, never guess whose resume to
attach. Revisit only if a popup counter shows rung 3 firing often.

### `POST /plan`

Composes `resolve_tailored_resume()` (`:465`) + `build_application_plan()` (`:401`) +
`readiness_report()` (`:434`) itself — **not** `plan_for_job()` (`:669`), because routing is off the
live page URL, which `plan_for_job()` doesn't take as input. Restate this in the module docstring
every time this file is touched (see `step-15a`'s note).

### `GET /resume/meta`

`?page_id=` → `{filename, size, mime, abs_path}`. No bytes. Exists so the popup (`step-15c`) can
show *"will attach: X.docx"* before the human clicks anything, and so `step-15d` doesn't have to
invent this lookup later.

### LinkedIn / Indeed — server-side, keyed on the live URL

`_READONLY_CHANNELS = {"linkedin", "indeed"}` from `detect_apply_channel(live_page_url)`. Enforced
**in the bridge**, so a bug or a hand-edited content script cannot bypass it. `FILLABLE_CHANNELS`
stays untouched — it governs the Playwright layer and should keep meaning exactly that.

One post-pass after `build_application_plan()` rewrites every entry to `review_required` /
`value: None` / `source: "channel read-only (linkedin/indeed) — never filled"`, independent of
profile completeness.

**Critical:** key on the **live page** URL, never the matched row's. A LinkedIn *posting* whose
Apply button bounced you to a Greenhouse or Cisco form is a page that *should* be filled.

## Reused verbatim

`build_application_plan()` `:401` · `readiness_report()` `:434` · `_resolve_field()` `:340` (incl.
the `resume-missing` branch at `:347-350`) · `detect_apply_channel()` `:111` ·
`parse_greenhouse_url()` `:127` · `fetch_greenhouse_questions()` `:165` (still preferred on
Greenhouse, DOM as fallback) · `resolve_tailored_resume()` `:465`.

## Files

**New (extends `step-15a`'s file):** `scripts/autoapply_server.py` gains `handle_plan`,
`identify_job`, `_dom_to_schema`, `_READONLY_CHANNELS`. `tests/test_autoapply_job_match.py`.
**Modified:** `tests/test_autoapply_server.py` (adds `/plan` and `/resume/meta` cases).

**Conftest gotcha:** drafting isn't in this story, but `/plan` already imports from
`scripts.autoapply`, whose `ai_chat` is bound at import (`conftest.py:11-17`) — if any test in this
story's suite touches a code path that calls `ai_chat`, patch `patch_ai_chat(autoapply)`, not
`(autoapply_server)`.

## Verification

0. A `/plan` request carrying a known `page_id` returns that job's plan directly (rung 0), without
   touching the URL-matching candidate pool — verify by asserting no candidate-pool lookup occurs
   (e.g. via a mock/spy) when `page_id` is present, even for a live page URL that would otherwise
   ambiguously match rung 3.
1. A DOM payload equivalent to `SAMPLE_QUESTIONS` (`autoapply.py:191`) yields a field-for-field
   identical plan — **this is the proof the bridge adds no logic.**
2. LinkedIn and Indeed page URLs → every field `review_required`, with a fully populated profile.
3. Match, one case per rung: exact · normalized (`?gh_src=`, trailing `/apply`, `job-boards.`) ·
   `?gh_jid=` · **two matches → `ambiguous`, picks neither** · no match → resume `review_required`
   (source `resume-missing`) while everything else resolves · **a row at `Application Queued` still
   matches** (catches a naive `Resume Tailored`-only pool).
4. `/plan` writes no status to any page (read-only endpoint).
5. `/resume/meta` returns filename/size/mime/path with no bytes; works even on a read-only channel
   (path display isn't "filling").

## Risks (carried from the epic, load-bearing here)

`isTrusted`/synthetic-event risk doesn't apply to this story (no DOM writes yet). The rung-3
"ask" fallback is the one place a wrong match could silently attach the wrong resume later — the
≥2-matches-falls-through rule is the whole mitigation; don't weaken it under pressure to "just pick
the most recent."
