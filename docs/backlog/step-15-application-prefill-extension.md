# Step 15 — Application pre-fill browser extension (Stage 7 Layer 3)

**Status:** finalized, queued, not started (2026-07-30). Size **L** overall, split
2026-07-30 into seven small stories (`step-15a`…`step-15g`) so each ships and is verifiable on
its own, then extended 2026-07-31 with two more (`step-15h`, `step-15i`) folding in a docked
side-panel job launcher, and extended again 2026-08-01 with a tenth (`step-15j`) so the bridge
auto-launches instead of requiring a manually-run terminal command — see "Sub-stories" below.
This doc is now the **epic**: shared why/architecture/decisions that don't belong to any one
increment. Depends on Step 10 Phases 1–2 (done). Folded from
`docs/refinement-plans/auto-apply/browser-extension-prefill.md`, which is deleted per the
one-doc-per-queued-story rule (the split below is a deliberate, noted exception to that rule —
each sub-story is still one doc per *increment*, not a duplicate spec).

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
 panel.js     match display, Applied     ──POST /confirm-applied──▶ db_update_status_verified()
```

**Front door (`step-15h`):** the docked side panel lists jobs at `Status = Resume Tailored` via
`GET /jobs/ready` (wraps `db_get_ready_to_apply()`, no new query logic), the user picks one, the
extension opens that job's apply URL itself (`chrome.tabs.create`), and the panel switches to the
plan view for that tab using the `page_id` it already knows — the rest of the flow above is
unchanged. `step-15i` extends this to N such job/panel pairs running at once, one per tab.

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
controls ship in v1 (in `step-15g`, not later) — see that story for the control table.

## Sub-stories

Split 2026-07-30 from the original monolithic checklist so each increment is independently
plannable, testable, and shippable — a partial-progress state (e.g. stopping after `step-15d`'s
go/no-go) is a coherent place to pause, not a half-finished feature. Each sub-story is
self-contained (own scope, checklist, verification, files) but leans on the architecture/decisions/
security/`Applied`-invariant context above rather than repeating it.

| Story | Increment | What it delivers | Standalone value | Size |
|---|---|---|---|---|
| [step-15a-serve-bridge-scaffold.md](step-15a-serve-bridge-scaffold.md) | 0 | `run.py --serve`, token file, `GET /health`, loopback bind, `ThreadingHTTPServer` | Foundation only | S |
| [step-15b-plan-endpoint-identify-job.md](step-15b-plan-endpoint-identify-job.md) | 1 | `POST /plan` + `identify_job()` (3 rungs) + `GET /resume/meta` | Machine-readable planner; `/resume/meta` alone kills the Notion round-trip | M |
| [step-15c-extension-readonly-overlay.md](step-15c-extension-readonly-overlay.md) | 2 | Side-panel shell: scrape → badge/overlay, panel shows match + resume filename + Copy path | Already beats the HTML answer sheet; works on every site | S |
| [step-15d-resume-attach.md](step-15d-resume-attach.md) | 3a | `GET /resume` bytes + DataTransfer attach only | **The headline win — go/no-go checkpoint** | M |
| [step-15e-field-fill.md](step-15e-field-fill.md) | 3b | Fill text/select fields where `status == "ready"` | Removes repetitive typing | S |
| [step-15f-essay-drafts.md](step-15f-essay-drafts.md) | 4 | Interactive draft panel + `POST /drafts` | Removes essay retyping | S |
| [step-15g-confirm-applied.md](step-15g-confirm-applied.md) | 5 | `POST /confirm-applied` + panel button | Removes the Notion round-trip | S |
| [step-15h-job-list-launcher.md](step-15h-job-list-launcher.md) | 6 | `GET /jobs/ready` + side-panel job list + extension-initiated navigation (`identify_job()` rung 0) | Extension picks the job instead of the human navigating first | S |
| [step-15i-multi-session-state.md](step-15i-multi-session-state.md) | 7 | Per-tab session state (`Map<tabId, {...}>`) in `background.js`, soft cap on concurrent sessions | N parallel job/panel sessions instead of one at a time | S |
| [step-15j-standalone-native-launch.md](step-15j-standalone-native-launch.md) | 8 | Native-messaging host that auto-launches `python run.py --serve` and auto-populates the token, so the extension never requires a manually-run terminal command | Removes the standing setup/launch step for every session, not just the first | M |

Order matters: `a`→`b`→`c` are sequential (each needs the previous endpoint/scaffold). `d` (resume
attach) is the **go/no-go checkpoint** — see Risk 2 below — decide there before investing in `e`/`f`/`g`,
which are independent of each other and of `d` once `c` exists. `h` (job list + launcher) depends
on `b` (needs the rung-0 identify path) and `c` (needs the panel shell to render into), and is
independent of `d`/`e`/`f`/`g`. `i` (multi-session state) depends only on `h`. `j` (standalone
native launch) depends only on `a` (the `--serve`/token-file/`--health` contract it wraps) and `c`
(the panel/options surfaces it edits) — independent of `d` through `i`, since it changes how the
bridge process starts, not anything it serves once started. The docs closeout
(`CLAUDE.md`/`CHANGELOG.md`) is not its own numbered story; each sub-story updates its own slice as
it ships (see "Testing a Change" in the root `CLAUDE.md`), and "Docs lifecycle" below tracks the
one-time doc moves already done plus what's left at final close-out.

### Reused verbatim across every sub-story — this is the architectural claim, and it holds

`build_application_plan()` `autoapply.py:401` · `readiness_report()` `:434` · `_resolve_field()`
`:340` (incl. the `resume-missing` branch at `:347-350`, which makes "no Notion match" a supported
state with **no new code**) · `detect_apply_channel()` `:111` · `parse_greenhouse_url()` `:127` ·
`fetch_greenhouse_questions()` `:165` (still preferred on Greenhouse, DOM as fallback) ·
`resolve_tailored_resume()` `:465` (already handles `file://` and CI `raw.githubusercontent.com`) ·
`draft_free_text_answers()` `:607` (already leaves `status`/`value` untouched at `:642`) ·
`_resume_text_for()` `:647` · `db_get_jobs()` / `db_get_job_description()` /
`db_update_status_verified()` at `utils.py:941` / `:919` / `:876` · `db_get_ready_to_apply()`
`utils.py:907` — backs `step-15h`'s `GET /jobs/ready`, no new Notion query logic.

**The only genuinely new logic is `_dom_to_schema()`** (in `step-15b`) — keep it a pure function so
it unit-diffs against `SAMPLE_QUESTIONS`. Plus one extraction: `accepts_docx(accept_attr)` pulled
out of `autoapply_browser.py:102-112` (in `step-15d`) so the bridge and Layer 2 share one rule.

## Risks

1. **`isTrusted: false`** — some ATS validators and dropzones reject synthetic events; nothing a
   content script can do. Expect a nonzero per-site failure rate. Mitigated by the tier-3 copy-path
   fallback and verify-don't-claim (`step-15d`).
2. **`step-15d` is the go/no-go.** If attach readback fails broadly across Ashby and a custom career
   site, the headline win is gone, and what remains (path display, Applied confirm, read-only
   overlay) may not justify a second UI surface. Decide there, not at the end — don't start
   `step-15e`/`f`/`g` until `step-15d`'s live verification (its own checklist item 10) passes.
3. **Workday stays largely unsolved** — see "Honestly not solved" above.
4. **The Applied button is a habit risk**, not just a code risk: it is right there and easy to click
   before you have actually submitted. The audit line (`step-15g`) is the mitigation; residual risk
   accepted knowingly.
5. **Maintenance** — a second UI in a language with no test runner here. Keep the JS thin, rely on
   grep + Python contract tests, and **do not** add a JS test runner in v1. If `content.js` starts
   needing unit tests, logic has leaked out of Python; push it back.
6. **Mild SSRF shape** in `_download_tailored_resume()` (`autoapply.py:493`) now that a browser
   request can trigger it. The URL comes from the user's own Notion DB, so risk is low — constrain
   the fetch host to `raw.githubusercontent.com` (handled in `step-15d`).

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
- This monolithic doc split into the epic + seven `step-15a`…`step-15g` stories above.

**Done 2026-07-31, still before implementation started:**
- `refinement-plans/auto-apply/step-15-interactive-launcher.md` (docked side-panel job launcher:
  job list, extension-initiated navigation, multi-session panes) finalized against its 4 open
  questions and folded in: `step-15c` retitled/rescoped from "popup + overlay" to "side-panel
  shell"; `step-15b` gains `identify_job()`'s rung 0 (known `page_id`); `step-15f` retitled to
  "interactive draft panel" (same contract, panel container); new `step-15h` (job list + launcher)
  and `step-15i` (multi-session state) added. The proposal's general `POST /status` route was
  **not** adopted — `step-15g`'s `/confirm-applied` remains the only status write the extension
  makes — and ATS token/board write-back was **deferred to Step 13**, not built here. Source doc
  **deleted**; both `README.md` index files updated.

**Done 2026-08-01, still before implementation started:** `step-15j` (standalone native launch)
added: a native-messaging host that auto-starts the bridge and auto-populates the token, removing
the manual `python run.py --serve` + copy-paste-token step on the happy path. No source doc to
delete (designed directly as a queued story, not folded from a refinement-plan). `README.md`
backlog index updated.

**Remaining, at final close-out (after `step-15j`):** `CLAUDE.md` gets a "Layer 3 — browser
extension" subsection under Stage 7 and the reformulated `Never Applied` paragraph
(`:339-343`); `docs/CHANGELOG.md` gets a Step 15 entry, and a backfilled Step 10 entry if cheap —
it currently has **none**.
