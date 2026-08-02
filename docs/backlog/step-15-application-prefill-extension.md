# Step 15 — Application pre-fill browser extension (Stage 7 Layer 3)

**Status:** finalized, queued, not started (2026-07-30). Size **L**. Depends on Step 10 Phases 1–2
(done). Folded from `docs/refinement-plans/auto-apply/browser-extension-prefill.md`, which is
deleted per the one-doc-per-queued-story rule.

## Goal

Cut the ~20 min/application spent in the browser, for **new inbound jobs only**. Not backlog
drainage — the 450 existing actionable rows are explicitly out of scope.

## Why this, and not more headless auto-apply

Stage 7's Playwright layer (`scripts/autoapply_browser.py`) gates on
`FILLABLE_CHANNELS = {greenhouse, lever}` — 15 of 450 actionable tracker rows. Three defects
compound past that headline:

1. **It rarely fills even where it routes.** `autoapply.py:757-760` — a job with any unresolved
   *required* field is marked `Needs Human: Question` and `continue`s **before** the browser opens.
   Both real-schema answer sheets in `output/applications/` hit that gate (Customer.io 65% of
   fields resolved, Anthropic 45%). Effective Greenhouse fill rate is near zero, not 3%.
   **Confirmed 2026-07-30, no longer an estimate:** a full-backlog dry run (`--stage 7 --dry-run
   --limit 341`, after filling the profile's last 7 blank presets) found 12/341 (3.5%) rows on
   Greenhouse, of which only 2 came back READY — **2/341 ≈ 0.6% of the backlog actually reaches
   the browser.** The other 9 blocked on required, company-specific knockout questions (e.g.
   Customer.io's "have you worked for a company that uses Customer.io") that no generic preset
   bank can ever close — see `docs/backlog/step-10-auto-apply-subsystem.md` §11 for the full
   per-job breakdown. Zero Lever rows exist in the tracker to measure at all.
2. **It runs anonymous.** `autoapply_browser.py:165-169` — fresh context, no cookies, no storage
   state. Anything behind a login is structurally unreachable. `_classify_block()` runs *once*
   after navigation, so a late-mounting captcha surfaces as `drift`, not `captcha`.
3. **The proposed extension of it has a ~13% ceiling.** `resolve_ats_posting()` + `gh_jid`
   detection + ashby converts ~9/69 sampled rows — and each still has to clear defects 1 and 2.

So the real ceiling is 13% × (fields fully resolved) × (no auth wall) × (no late captcha).

### The scoping error that parked this plan (do not re-derive)

`sourcing-bottleneck-analysis.md` sized an extension at "~18 Indeed jobs" and concluded it wasn't
worth building. **That number counted rows the pipeline can auto-route to a fillable URL.** An
extension routes nothing — the human navigates, and it fills whatever form is on screen. Its
denominator is *every application opened by hand*: Workday, Ashby, vanity-domain Greenhouse, and
the Phenom-style career sites reached **through** a LinkedIn posting.

The measured "LinkedIn exposes no apply URL, 0/20" finding constrains *automated routing* and says
nothing about a human already standing on the form. That is the single reason this moved from
parked to queued, and it is the claim most likely to be re-litigated later.

### Why the extension is a different substrate, not an increment

Playwright needs to *derive* the URL, *know* the schema, and *survive* auth/captcha anonymously.
The extension removes all three at once: you navigate, the live DOM is the schema, and you are
already past auth and captcha. Ashby, Workday and arbitrary custom forms become one code path.

**Honest cost:** a second UI surface in a language this repo has no test runner for, an HTTP bridge
that serves personal data to a browser, and it is **interactive only** — it does nothing for an
unattended run, so it complements the Playwright layer rather than replacing it.

**Honestly not solved:** per-ATS account creation and email verification (Workday tenants). Being
logged in helps, but the tenant account must already exist. Do not gate this project on Workday.

## Architecture

The content script scrapes the live DOM into the **exact schema shape `build_application_plan()`
already consumes**, so every answer decision stays in Python and nothing is ported to JS.

```
Chrome                                   127.0.0.1:8765 (python run.py --serve)
 content.js   scrape form → questions[]  ──POST /plan──▶  build_application_plan()   [unchanged]
              fill status=="ready"       ◀──plan JSON───  readiness_report()         [unchanged]
 drafts.js    per-field Insert           ──POST /drafts─▶ draft_free_text_answers()  [unchanged]
 background.js  holds token, fetches     ──GET /resume──▶ resolve_tailored_resume()  [unchanged]
 popup.js     match display, Applied     ──POST /confirm-applied──▶ db_update_status_verified()
```

**Routing is off the live page URL, never the Notion row's URL** — those routinely differ, and that
difference is the entire premise. `plan_for_job()` (`autoapply.py:669`) is therefore **not reused**;
the bridge composes `resolve_tailored_resume` + `build_application_plan` + `readiness_report`
itself. Say this in the module docstring — it is the likeliest silent mistake.

### Settled decisions

| Decision | Choice | Why |
|---|---|---|
| Architecture | Local Python bridge; extension is a thin DOM client | All answer logic stays in `autoapply.py`, so nothing can drift |
| Fill behavior | Fill `ready` fields **on click**, badge the rest | Never on load — a wrong eligibility answer is unretractable |
| Scope | Every form **except LinkedIn/Indeed**, which stay read-only overlay | Preserves the existing permanent rule |
| Distribution | Unpacked / developer-mode only | A store listing for something that reads application forms is a different review problem |
| Fetch location | MV3 **service worker**, not the content script | `host_permissions` avoids CORS preflight for the auth header, and the token never enters a page that shares a DOM with the job site |

### Security (non-negotiable)

Bind `("127.0.0.1", port)` **explicitly** — `HTTPServer(("", port))` binds all interfaces. Random
token in git-ignored `config/extension_token.txt`, regenerated per `--serve`, checked on every
request. CORS echoed **by page origin, not extension id** — an unpacked extension's id changes on
reload, so any id-keyed allowlist silently breaks. Runs only under an explicit `python run.py
--serve`; never a daemon. `ThreadingHTTPServer` so a slow draft doesn't block a concurrent
`/resume`.

## The `Applied` invariant — reformulated, not broken

`WRITABLE_STATUSES` excludes `Applied` (`autoapply.py:65-80`), asserted by
`tests/test_autoapply_notion.py:50-63`. The rationale (`autoapply.py:67-71`) is that comparable
tools mark jobs applied that were never submitted — **inference from an unobservable event**. That
same comment already names the permitted case: "set by the human, by hand, after they click
Submit." It only assumed that hand was in Notion's UI.

> **New formulation:** `Applied` is never *inferred*. Planning and fill paths cannot write it. It
> may be written only by a dedicated confirmation route that is reachable solely from an explicit
> human gesture, carries no plan/fill data, and records in the tracker that the claim came from the
> human.

**What genuinely weakens:** today the guarantee is *physical* — no code path exists. After this,
one process holds both a credential and a path to the write. The threat model shifts from "the tool
lies" to "a bug or a future refactor reaches the write without a human keystroke." Compensating
controls ship in v1, not later:

| # | Control |
|---|---|
| 1 | `WRITABLE_STATUSES` stays byte-identical. New `HUMAN_CONFIRMED_STATUS` / `CONFIRMABLE_STATUSES` live in `autoapply_server.py`; a test asserts the sets are disjoint |
| 2 | Route is **`POST /confirm-applied`**, not a generic `POST /status`. The status literal is hard-coded in the handler body and the route **accepts no status field** — no data path from a computed value to the write |
| 3 | Body requires `confirmed_by == "human"`, else 400 |
| 4 | `page_id` (string) only; a list is explicitly rejected. "Mark the backlog applied" is structurally never one call away |
| 5 | The confirm button lives in `popup.js`. `content.js` must contain no reference to `confirm-applied` or `applied` — enforced by extending the existing grep test |
| 6 | Write via `db_update_status_verified()` (`utils.py:876`), setting `Date Applied` and `Application Log = "<date> Applied — human-confirmed via extension"`. Every tool-mediated `Applied` is labelled and auditable — this is what replaces the lost "cannot happen" proof |

Existing tests are **kept verbatim** (both still true, and now more load-bearing);
`test_source_has_no_submit_click` (`:66`) is *parametrized* over more files rather than replaced.
No Notion schema change needed — `Applied` is already a status.

## Implementation checklist

| # | Increment | Standalone value |
|---|---|---|
| 0 | `run.py --serve [--port]`, token file, `GET /health`, loopback bind, `ThreadingHTTPServer` | — |
| 1 | `POST /plan` + `identify_job()` (3 rungs) + `GET /resume/meta` | machine-readable planner; `/resume/meta` alone kills the Notion round-trip |
| 2 | Extension read-only: scrape → badge/overlay, popup match + resume filename + **Copy path** | already beats the HTML answer sheet; works on every site |
| **3a** | `GET /resume` bytes + **DataTransfer attach only** | **the headline win — go/no-go checkpoint** |
| 3b | Fill text/select fields where `status == "ready"` | removes repetitive typing |
| 4 | Draft panel + `POST /drafts` | removes essay retyping |
| 5 | `POST /confirm-applied` + popup button | removes the Notion round-trip |
| 6 | Docs (see bottom) | — |

3a precedes 3b deliberately: the file attach carries **zero eligibility risk** (it fills no answer
content), and it is the mechanism most likely to vary per site — measure it before investing in 3b.

### Reused verbatim — this is the architectural claim, and it holds

`build_application_plan()` `autoapply.py:401` · `readiness_report()` `:434` · `_resolve_field()`
`:340` (incl. the `resume-missing` branch at `:347-350`, which makes "no Notion match" a supported
state with **no new code**) · `detect_apply_channel()` `:111` · `parse_greenhouse_url()` `:127` ·
`fetch_greenhouse_questions()` `:165` (still preferred on Greenhouse, DOM as fallback) ·
`resolve_tailored_resume()` `:465` (already handles `file://` and CI `raw.githubusercontent.com`) ·
`draft_free_text_answers()` `:607` (already leaves `status`/`value` untouched at `:642`) ·
`_resume_text_for()` `:647` · `db_get_jobs()` / `db_get_job_description()` /
`db_update_status_verified()` at `utils.py:941` / `:919` / `:876`.

**The only genuinely new logic is `_dom_to_schema()`** — keep it a pure function so it unit-diffs
against `SAMPLE_QUESTIONS`. Plus one extraction: `accepts_docx(accept_attr)` pulled out of
`autoapply_browser.py:102-112` so the bridge and Layer 2 share one rule.

### `identify_job()` — 3 rungs, not the originally-specced 5

Candidate pool fetched once at boot and matched in-process. Pool is
`WRITABLE_STATUSES | {"Resume Tailored"}` — **not** `Resume Tailored` alone, since Stage 7's `run()`
moves rows off it (`autoapply.py:753`); a naive pool would miss exactly the jobs Stage 7 planned.

1. **Normalized URL** — drop query/fragment, strip trailing `/apply`, fold `job-boards.`→`boards.`,
   lowercase host, strip trailing slash. The workhorse. Exact-URL match is its degenerate case:
   report the higher confidence, but skip the `db_find_job_by_url()` round-trip (it returns only a
   page id, and no `db_get_job_by_page_id()` exists — rung 1 as originally specced forces a new
   helper plus a second read).
2. **Greenhouse `(board_token, job_id)`** via `parse_greenhouse_url()` — handles the `?gh_jid=` and
   `embed/job_app` shapes that normalization alone misses (`autoapply.py:147-160`).
3. **Ask** — popup lists candidates. With a pool near `AUTOAPPLY_DAILY_CAP`, a 2-second click.

**Cut for v1: fingerprint matching.** It is the only rung that can produce a *wrong* match, needs
new page-side JSON-LD/`og:title` scraping, and its value comes from a stale backlog — explicitly
out of scope. Keep the *rule*: ≥2 matches → fall through to ask, never guess whose resume to
attach. Revisit only if a popup counter shows rung 3 firing often.

**Board-token harvest, piggybacked on the same URL read (cross-ref: `docs/backlog/
step-13-board-token-harvesting.md`).** `identify_job()` already has to read the live page URL for
rung 1 and the `_READONLY_CHANNELS` check — a human standing on a real apply form is a stronger,
already-confirmed signal than anything Stage 1 scrapes or guesses. On each `/plan` request, also
call `sources.parse_board_url(live_page_url)` and, on a hit, write through Step 13's same
`harvest_board_tokens()` cache contract (`provenance: "observed"`, `observed_from`, `checked`) —
one added call, not a new registry or schema. Not required for 3a's go/no-go checkpoint; land it
whenever convenient once the bridge exists.

### Resume attach — the highest-frequency friction

Measured pain: locating the tailored resume path in Notion, then hunting the file in the OS
attachment dialog, on every application.

**Server.** `GET /resume/meta?page_id=` → `{filename, size, mime, abs_path}`, no bytes, so the popup
shows *"will attach: X.docx"* before you click. `GET /resume?page_id=&accept=<input's accept attr>`
→ bytes, with: a hard containment check (`Path(p).resolve()` must be under `RESUMES_DIR`, else 403 —
the Notion DB is user-editable and the browser is the caller); the shared `accepts_docx()` rule,
falling back to `render_docx.convert_docx_to_pdf()` for PDF-only forms (reusing Layer 2's decision
at `autoapply_browser.py:115-123`); `Content-Disposition` filename.

**Client.**

```js
const dt = new DataTransfer();
dt.items.add(new File([bytes], filename, {type: mime, lastModified: Date.now()}));
input.files = dt.files;
input.dispatchEvent(new Event('input',  {bubbles: true}));
input.dispatchEvent(new Event('change', {bubbles: true}));
```

**Dropzone strategy, three tiers:**
1. **Find the hidden input.** Greenhouse, Ashby, Workday, Dropzone.js, react-dropzone, Uppy and
   Filestack all still render a real `<input type=file>`, hidden via `display:none`/`opacity:0`/1px.
   Query across the document **including open shadow roots**, do **not** filter on visibility, and
   prefer the one nearest the labelled question container. Covers the large majority.
2. **Synthesize a drop** — `dragenter`→`dragover`→`drop` carrying the same `DataTransfer`.
   react-dropzone reads `event.dataTransfer.files` and accepts this.
3. **Fail loudly, usefully** — badge the field and surface the resolved absolute path with a *Copy
   path* button. Even this floor removes both the Notion lookup and the file hunt: paste into the
   OS dialog's filename box.

Do **not** attempt `input.click()` to open the OS dialog — user-gesture-gated and not scriptable.
Do not imply otherwise in the UI.

**Verify, never claim.** Read back `input.files[0]?.name` and report *"attached (verified)"* or
*"not attached"* — `autoapply_browser.py`'s rule #2 applied to Layer 3.

### Essays — review-and-insert, never auto-fill

`draft_free_text_answers()` already has the right contract; the work is entirely in surfacing.

- **Separate route `POST /drafts`**, not part of `/plan`: one AI call per question is 10–30s and
  would block the fill, and drafting should be its own gesture. Gated on `AUTOAPPLY_DRAFT_ESSAYS`
  (`settings.py:395`) and on `identify_job()` having matched (drafting needs the JD + resume text).
  Unmatched → no draft; the field stays plain `review_required`.
- **Enforcement is structural, not special-cased.** The filler iterates
  `fields.filter(f => f.status === "ready")` — the same predicate shape as
  `autoapply_browser.py:155`. A drafted field is `review_required`, so it is excluded by the *same*
  predicate that already excludes it. **Add no `draft` branch to the fill path.**
- **File separation makes that greppable:** fill loop in `content.js`, the entire draft panel and
  per-field Insert in `drafts.js`. Assert `draft` never appears in `content.js`.
- Insert is a separate gesture per field, never triggered by the main Fill button. After insert,
  re-badge *"inserted — edit before submitting."*

### LinkedIn / Indeed — server-side, keyed on the live URL

`_READONLY_CHANNELS = {"linkedin", "indeed"}` from `detect_apply_channel(live_page_url)`. Enforced
**in the bridge, not JS**, so a bug or a hand-edited content script cannot bypass it.
`FILLABLE_CHANNELS` stays untouched — it governs the Playwright layer and should keep meaning
exactly that.

One post-pass after `build_application_plan()` rewrites every entry to `review_required` /
`value: None` / `source: "channel read-only (linkedin/indeed) — never filled"`, independent of
profile completeness.

**Critical:** key on the **live page** URL, never the matched row's. A LinkedIn *posting* whose
Apply button bounced you to a Greenhouse or Cisco form is a page that *should* be filled.

**Line on `/resume`:** bytes are 403 on a read-only channel, but `/resume/meta` (filename + path) is
allowed and Copy-path works. Displaying and copying a file path is not automated applying — it is
the answer-sheet rule applied to a path. This is what makes the extension useful even on an Easy
Apply form, and it materially de-risks the volume question.

## Files

**New:** `scripts/autoapply_server.py` (handler + `_dom_to_schema` + `identify_job` +
`_READONLY_CHANNELS` + `HUMAN_CONFIRMED_STATUS`; **zero answer logic**) · `extension/`
(`manifest.json`, `background.js`, `content.js`, `drafts.js`, `overlay.css`, `popup.*`,
`options.*`) · `tests/test_autoapply_server.py` · `tests/test_autoapply_job_match.py` ·
`tests/test_autoapply_applied_confirmation.py` · `tests/test_run_serve_wiring.py`.

**Modified:** `run.py` (`--serve`/`--port`, mirroring the `--setup-profile` pattern at `:564` and
`:625`) · `tests/test_autoapply_notion.py` (parametrize the grep at `:66`; add the disjointness
test) · `scripts/autoapply_browser.py` (extract `accepts_docx()`) · `.gitignore`
(`config/extension_token.txt`) · `CLAUDE.md` (a "Layer 3 — browser extension" subsection under
Stage 7; reformulate the `Never Applied` paragraph at `:339-343`).

## Verification

Structure the server as a thin `BaseHTTPRequestHandler` over **pure functions** — `handle_plan`,
`handle_drafts`, `handle_confirm_applied`, `identify_job`, `_dom_to_schema` — so
`patch_notion_db(autoapply_server)` works like every existing stage test and only the token/CORS
tests need a real socket (bind port 0 in a thread). **Conftest gotcha:** drafting calls into
`scripts.autoapply`, whose `ai_chat` is bound at import (`conftest.py:11-17`) — patch
`patch_ai_chat(autoapply)`, not `(autoapply_server)`.

**Automated** (`pytest -v` green; `pytest -m browser` unaffected):
1. A DOM payload equivalent to `SAMPLE_QUESTIONS` (`autoapply.py:191`) yields a field-for-field
   identical plan — **this is the proof the bridge adds no logic.**
2. LinkedIn and Indeed page URLs → every field `review_required`, with a fully populated profile.
3. `/resume` bytes 403 on a read-only channel; `/resume/meta` allowed.
4. `/resume` refuses a `file://` path outside `RESUMES_DIR`; bad token rejected *before* any Notion
   read; bind literal is `"127.0.0.1"`; PDF-only form gets a converted PDF.
5. Match, one case per rung: exact · normalized (`?gh_src=`, trailing `/apply`, `job-boards.`) ·
   `?gh_jid=` · **two matches → `ambiguous`, picks neither** · no match → resume `review_required`
   (source `resume-missing`) while everything else resolves · **a row at `Application Queued` still
   matches** (catches a naive `Resume Tailored`-only pool).
6. Drafted field is never `ready`; drafts require a matched `page_id`.
7. Confirm: sets disjoint · missing `confirmed_by` → 400 with no write · happy path sets `Applied`
   + `Date Applied` on exactly one page · batch payload rejected · Notion-dropped status reported as
   failure (`db.known_statuses`, pattern at `test_autoapply_notion.py:84`) · `/plan` writes no
   status to any page.
8. Parametrized grep: `autoapply_browser.py` (tokens unchanged) + `content.js` (submit tokens,
   `confirm-applied`, `applied`, `draft`).

**Live, on forms you do not intend to submit** — Greenhouse (must match the CLI plan) → Ashby → one
custom careers page reached *through* a LinkedIn posting → Workday (expect partial):
9. Popup names the right role and the right `.docx`; re-open with `?gh_src=test` and via the
   `job-boards.` host — both still match. Open an untracked job: everything else fills, the resume
   is badged, and no other job's resume is attached.
10. **Attach readback on all four sites.** Where it fails, confirm the Copy-path fallback appears.
11. LinkedIn Easy Apply: nothing filled, `/resume` 403s, but filename + Copy path still work.
12. Submit untouched; DevTools Network shows no POST leaving the page until you click it.
13. Confirm button on a job you actually submitted → Notion shows `Applied`, `Date Applied`, and an
    `Application Log` containing `human-confirmed via extension`.

## Risks

1. **`isTrusted: false`** — some ATS validators and dropzones reject synthetic events; nothing a
   content script can do. Expect a nonzero per-site failure rate. Mitigated by the tier-3 copy-path
   fallback and verify-don't-claim.
2. **Step 3a is the go/no-go.** If attach readback fails broadly across Ashby and a custom career
   site, the headline win is gone, and what remains (path display, Applied confirm, read-only
   overlay) may not justify a second UI surface. Decide there, not at the end.
3. **Workday stays largely unsolved** — see "Honestly not solved" above.
4. **The Applied button is a habit risk**, not just a code risk: it is right there and easy to click
   before you have actually submitted. The audit line is the mitigation; residual risk accepted
   knowingly.
5. **Maintenance** — a second UI in a language with no test runner here. Keep the JS thin, rely on
   grep + Python contract tests, and **do not** add a JS test runner in v1. If `content.js` starts
   needing unit tests, logic has leaked out of Python; push it back.
6. **Mild SSRF shape** in `_download_tailored_resume()` (`autoapply.py:493`) now that a browser
   request can trigger it. The URL comes from the user's own Notion DB, so risk is low — constrain
   the fetch host to `raw.githubusercontent.com` while in there.

## Considered and dropped

**Ashby in `FILLABLE_CHANNELS` (the Playwright route).** `refinement-plans/auto-apply/SESSION_STATUS.md` measured 4 of 9
matched aggregator rows resolving to Ashby boards, which re-triggered
`refinement-plans/auto-apply/ashby-workday-custom-fill.md`'s Option A. Dropped because this
extension covers Ashby *interactively* with no per-ATS schema or selector work, which is this
story's scope. **It is not covered for an unattended nightly run** — revive Option A if
hands-off applying becomes a goal. That doc is deleted when this story ships, per its own
instruction (`:207-210`) and `refinement-plans/README.md:55-60`; this paragraph is the harvest.

## Docs lifecycle

**Done 2026-07-30, before implementation started:**
- `browser-extension-prefill.md` folded into this story and **deleted**, per the
  one-doc-per-queued-story rule.
- `ashby-workday-custom-fill.md` **deleted** — superseded; its one live idea is harvested under
  "Considered and dropped" above.
- `SESSION_STATUS.md` **deleted** — a point-in-time note, per its own header.
- `sourcing-bottleneck-analysis.md` **kept, with a dated correction header.** It is an *analysis*,
  not a plan, and holds findings that must never be re-derived: LinkedIn 0/20 apply-URL fields,
  `followApplyRedirects` +64% wall-clock against a 400s budget, authenticated-LinkedIn rejected on
  account-risk grounds. Only its *recommendation* (lines 71-74, "Don't build the extension now…
  ~18 jobs is a poor trade") is superseded, by the denominator correction at the top of this story.
  **Nothing was deleted from it.** Note it still names the two deleted docs in prose — historical
  record, left as-is.
- Both `README.md` index files updated.

**Remaining, at step 6:** `CLAUDE.md` gets a "Layer 3 — browser extension" subsection under Stage 7
and the reformulated `Never Applied` paragraph (`:339-343`); `docs/CHANGELOG.md` gets a Step 15
entry, and a backfilled Step 10 entry if cheap — it currently has **none**.
