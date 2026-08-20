# Plan

Implementation, by increment. Order/dependency: `0`→`1`→`2` are sequential (each needs the
previous endpoint/scaffold). `3a` (resume attach) was the **go/no-go checkpoint**. `3b`/`4`/`5` are
independent of each other and of `3a` once `2` exists. `6` (job list + launcher) depends on `1`
(rung 0) and `2` (panel shell), independent of `3a`-`5`. `7` (multi-session) depends only on `6`.
`8` (native launch) depends only on `0` and `2` — it changes how the bridge process starts, not
anything it serves once started.

## 0 — `run.py --serve` bridge scaffold

The skeleton every later increment attaches routes to: `run.py --serve [--port]` (mirrors the
`--setup-profile` pattern), `scripts/autoapply_server.py` as a `BaseHTTPRequestHandler` subclass
over `ThreadingHTTPServer`, explicit `("127.0.0.1", port)` bind, a random token regenerated per
invocation and written to git-ignored `config/extension_token.txt`, and `GET /health` (no auth) so
a human/extension can probe liveness without a token round-trip. CORS policy (echo the request's
own `Origin`, never an extension-id allowlist) decided here even before any real route exists.

**Files:** `scripts/autoapply_server.py` (new), `run.py` (`--serve`/`--port`), `.gitignore`
(`config/extension_token.txt`), `tests/test_autoapply_server.py`, `tests/test_run_serve_wiring.py`.

## 1 — `POST /plan` + `identify_job()` + `GET /resume/meta`

Makes the bridge answer "what should go in this form, and whose job is this" from a DOM payload
alone.

- **`_dom_to_schema()`** — the one genuinely new piece of answer-adjacent logic in the whole
  project. A pure function (DOM payload in, schema-shape dict out), unit-diffed against the
  existing `SAMPLE_QUESTIONS` fixture (`autoapply.py:191`) — that diff is the proof this bridge
  adds no answer logic of its own.
- **`identify_job()`** — candidate pool fetched once and matched in-process. Pool is
  `WRITABLE_STATUSES | {"Resume Tailored"}`, not `Resume Tailored` alone, since Stage 7's `run()`
  moves rows off it — a narrower pool would miss exactly the jobs Stage 7 already planned. Four
  rungs, in order:
  0. **Known `page_id`** — when the request already carries one (the side panel's job list,
     increment 6, opened this tab itself), short-circuit straight to that job, skipping the
     candidate pool and rungs 1-3 entirely. Only fires for launcher-opened tabs.
  1. **Normalized URL** — drop query/fragment, strip trailing `/apply`, fold `job-boards.`→
     `boards.`, lowercase host, strip trailing slash. The workhorse; exact-URL match is its
     degenerate case.
  2. **Greenhouse `(board_token, job_id)`** via `parse_greenhouse_url()`, for `?gh_jid=` and
     `embed/job_app` shapes normalization alone misses.
  3. **Ask** — no rung-1/2 hit returns the whole candidate pool for a human to pick from (rendered
     in the side panel, increment 2).
  Two or more matches at any rung is `ambiguous` and picks **neither** — fingerprint-style guessing
  was cut for v1 precisely because a wrong guess would attach the wrong resume.
- **`POST /plan`** composes `resolve_tailored_resume()` + `build_application_plan()` +
  `readiness_report()` itself — **not** `plan_for_job()`, since routing is off the live page URL,
  which `plan_for_job()` doesn't take as input.
- **`GET /resume/meta`** — `?page_id=` → `{filename, size, mime, abs_path}`, no bytes. Lets the
  panel show "will attach: X.docx" before the human clicks anything, ahead of increment 3a needing
  this lookup.
- LinkedIn/Indeed enforcement — see constraints.md.

**Files:** `scripts/autoapply_server.py` gains `handle_plan`, `identify_job`, `_dom_to_schema`,
`_READONLY_CHANNELS`. `tests/test_autoapply_job_match.py` (new), `tests/test_autoapply_server.py`
(extended).

## 2 — Side-panel shell + read-only extension overlay

The first browser-visible artifact: an unpacked MV3 extension that scrapes the page, calls `/plan`,
and **shows** the result — writes nothing to any form yet. Already beats the static HTML answer
sheet, and works on every site including LinkedIn/Indeed as a read-only overlay.

- Content script scrapes the live form into `_dom_to_schema()`'s expected shape, POSTs to `/plan`,
  renders the response as badges next to each question (`ready` / `review_required` / read-only) —
  display only.
- Docked side panel (`panel.html`/`panel.js`, via `chrome.sidePanel`) shows matched job
  title/company (or the rung-3 candidate list when ambiguous), the resume filename from
  `/resume/meta`, and a **Copy path** button using `abs_path` — no file bytes cross the wire yet.
- Token read from the options page, sent as an auth header from the background service worker
  only — never reaches `content.js`, `panel.js`, or the page's own DOM/JS context.
- LinkedIn/Indeed render the same read-only badges the bridge already returns — no special-casing
  needed client-side, since the server already did the rewrite. This is the proof point that
  enforcement lives server-side, not in JS.
- Distribution: unpacked/developer-mode only.

**Files:** `extension/manifest.json`, `extension/background.js`, `extension/content.js`,
`extension/overlay.css`, `extension/panel.html`, `extension/panel.js`, `extension/options.html`,
`extension/options.js`. `tests/test_autoapply_notion.py` starts parametrizing a grep test over
`content.js`/`panel.js` asserting no submit-token, no `confirm-applied`, no `applied`, no `draft`
reference — tokens that only start meaning something in later increments, so their absence here
catches scope creep early.

## 3a — Resume attach (`GET /resume` + DataTransfer) — the go/no-go checkpoint

The headline win: attach the correct tailored resume to the form's upload field with one click,
verified by reading the input back. Carries the least eligibility risk of any increment (fills no
answer content), so it was measured before field fill (3b) was built.

- **`GET /resume?page_id=&accept=`** → bytes, with a hard containment check (`Path(p).resolve()`
  must sit under `RESUMES_DIR`, else 403 — the Notion DB is user-editable and the browser is the
  caller), the shared `accepts_docx()` rule (extracted from `autoapply_browser.py` so Layer 2 and
  Layer 3 share one rule) falling back to `render_docx.convert_docx_to_pdf()` for PDF-only forms,
  a `Content-Disposition` filename set from the resolved file (never client input), and a 403 (no
  bytes) on a read-only channel — `/resume/meta` stays allowed there, only bytes are gated.
  `_download_tailored_resume()`'s fetch host is constrained to `raw.githubusercontent.com` here,
  closing a mild SSRF shape now that a browser request can trigger it.
- **Client DataTransfer attach:** build a `DataTransfer`, assign `input.files`, dispatch
  `input`/`change`.
- **Three-tier dropzone strategy:** (1) find the hidden `<input type=file>` — Greenhouse, Ashby,
  Workday, Dropzone.js, react-dropzone, Uppy, Filestack all still render a real one, hidden via
  CSS; query across the document including open shadow roots, don't filter on visibility; (2)
  synthesize a `dragenter`→`dragover`→`drop` sequence carrying the same `DataTransfer` for
  dropzone libraries that only read `event.dataTransfer.files`; (3) fail loudly and usefully —
  badge the field and surface the resolved absolute path with a Copy-path button. Never attempt
  `input.click()` (user-gesture-gated, not scriptable).
- **Verify, never claim:** read back `input.files[0]?.name` and report "attached (verified)" or
  "not attached" — mirrors `autoapply_browser.py`'s own rule.

**Files:** `extension/content.js` (attach logic), `scripts/autoapply_server.py` (`/resume`),
`scripts/autoapply_browser.py` (`accepts_docx()` extraction), `tests/test_autoapply_server.py`
(extended).

**Outcome:** live verification passed broadly enough to proceed — field fill (3b), drafts (4), and
confirm-applied (5) were built on top of it, so the go/no-go resolved "go."

## 3b — Field fill on click

The Fill loop: writes `status == "ready"` values into the page **only on an explicit click**,
never on load or on plan-fetch — a wrong eligibility answer is unretractable, so the human gesture
stays required for every run, not just the first.

- Fill predicate mirrors `autoapply_browser.py`'s `ready = [f for f in plan["fields"] if
  f["status"] == "ready"]` exactly, so Layer 2 and Layer 3 agree on what "ready" means without
  sharing code.
- Per DOM type: text/textarea write `.value` + dispatch `input`/`change`; `<select>` matches the
  option whose visible label equals `"Yes"`/`"No"`/`str(value)` (mirroring
  `autoapply_browser.py`'s `select_option(label=...)` rule) before falling back to matching on
  option `value`; radio groups are looked up by `name` across the whole document (not just the one
  element `scrapeForm()` originally mapped, since sibling radios share a `name`) and the matching
  option is checked; a lone checkbox gets `.checked = !!value`.
  LinkedIn/Indeed fields arrive pre-rewritten to `review_required` by the bridge, so they're
  excluded by the same `status == "ready"` filter with no extra client-side logic.
- After filling, each field is re-badged distinct from an unfilled `review_required` one, so a
  glance at the form shows what's left to do by hand.

**Files:** `extension/content.js` (fill loop, plus a fixed "Fill N ready fields" button),
`extension/overlay.css` (`.cpai-fill-btn`, `.cpai-badge--filled`).

**Risk carried forward:** the same `isTrusted: false` caveat as increment 3a — a synthetic
`input`/`change` event may not satisfy every framework's validation state (e.g. a React-controlled
input that only trusts its own `onChange`). Where this happens, the field stays visibly unfilled
rather than silently wrong.

## 4 — Interactive draft panel + `POST /drafts`

Removes essay retyping without ever auto-filling one: an AI-drafted answer per free-text question
for the human to read, edit, and insert — a separate gesture per field, never triggered by the
Fill button.

- **`POST /drafts`** is a separate route from `/plan` on purpose: one AI call per question is
  10-30s and would block every fill if bundled in. Gated on `AUTOAPPLY_DRAFT_ESSAYS` and a
  resolved `page_id` (no match → no draft, field stays plain `review_required`). Calls
  `draft_free_text_answers()` verbatim against the caller-supplied plan (the exact object the
  caller's own `/plan` call returned) plus the matched job's cached JD and tailored resume text
  (`_resume_text_for()`); adds a `draft` key per field, leaves `status`/`value` untouched.
- **`extension/drafts.js`** (a separate file from `content.js` on purpose, so the "no `draft` token
  in `content.js`" grep test stays meaningful): renders one drafted answer per free-text question
  with a per-field Insert button. Insert writes the (possibly human-edited) textarea contents into
  that one field and messages `content.js` (a generic `CPAI_INSERT_FIELD_VALUE` message — content
  script has no concept of "draft," it just writes a named field's value like any other write in
  that file) to re-badge it *"inserted — edit before submitting"* — never "done."
- **Enforcement is structural, not special-cased:** the fill loop (3b) already excludes anything
  that isn't `status == "ready"`; a drafted field stays `review_required`, so it's excluded by the
  same predicate with no `draft`-aware branch anywhere in the fill path.

**Files:** `extension/drafts.js` (new), `scripts/autoapply_server.py` (`build_drafts_response`,
`handle` wiring), `extension/panel.html` (drafts section), `tests/test_autoapply_drafts_endpoint.py`
(new). **Conftest gotcha:** drafting calls into `scripts.autoapply`, whose `ai_chat` is bound at
import — tests patch `patch_ai_chat(autoapply)`, not `(autoapply_server)`.

## 5 — `POST /confirm-applied` + panel button

Removes the Notion round-trip after a real submit: one explicit button that records `Applied` in
Notion, with an audit trail proving the claim came from a human click, not from planning or fill
code. The highest-stakes increment in the whole project — see the `Applied` invariant in
constraints.md.

Every control ships together, not incrementally:

| # | Control |
|---|---|
| 1 | `WRITABLE_STATUSES` stays byte-identical. New `HUMAN_CONFIRMED_STATUS`/`CONFIRMABLE_STATUSES` live in `autoapply_server.py`; a test asserts the sets are disjoint |
| 2 | Route is `POST /confirm-applied`, not a generic `POST /status`. The status literal is hard-coded in the handler body; the route accepts no status field at all |
| 3 | Body requires `confirmed_by == "human"`, else 400 |
| 4 | `page_id` (string) only; a list is explicitly rejected — "mark the backlog applied" is structurally never one call away |
| 5 | The confirm button lives in `panel.js` only. `content.js` contains no reference to `confirm-applied` or `applied` — enforced by the same grep test increment 2 started |
| 6 | Write via `db_update_status_verified()`, setting `Date Applied` and `Application Log = "<date> Applied — human-confirmed via extension"` — every tool-mediated `Applied` write is labelled and auditable |

The confirm button only ever appears once a job is actually resolved (`known`/`matched`), and only
carries the `page_id` the panel itself resolved.

**Files:** `scripts/autoapply_server.py` (`HUMAN_CONFIRMED_STATUS`, `CONFIRMABLE_STATUSES`,
`build_confirm_applied_response`), `extension/panel.html`/`panel.js` (confirm button + status
text), `extension/background.js` (`CONFIRM_APPLIED` message), `tests/test_autoapply_applied_confirmation.py`
(new). `tests/test_autoapply_notion.py`'s submit-click grep is parametrized to cover `panel.js`
with the plain submit-click ban only (it legitimately references "applied" now), while
`content.js` keeps the full ban including `confirm-applied`/`applied`/`draft`.

**Risk carried forward:** the Applied button is a habit risk, not just a code risk — it's right
there and easy to click before actually submitting. The audit line is the mitigation; this
residual risk is accepted knowingly, not solved.

## 6 — Job list + launcher

Flips the trigger direction: instead of the human navigating to a job first and the extension
guessing whose job it is, the side panel lists jobs at `Status = Resume Tailored` and the
extension opens the one the human picks — so the `page_id` is known before navigation.

- **`GET /jobs/ready`** wraps `db_get_ready_to_apply()` verbatim (`Status = "Resume Tailored"`,
  `Date Applied` empty, sorted by score desc) — no new Notion query logic. Returns
  `{page_id, title, company, url, score, tailored_resume_link}` per row.
- **Side panel job-list view** — the default view when the panel has no active job for the current
  tab: a scrollable, score-sorted list, refreshed on panel open.
- **Extension-initiated navigation** — `background.js`'s click handler: `chrome.tabs.create({url:
  job.url})`, then `sidePanel.setOptions({tabId, path: "panel.html?page_id=..."})` so that tab's
  panel switches to the plan view. The content script loads as usual and calls `/plan` carrying
  the known `page_id`; increment 1's rung 0 short-circuits straight to that job.

**Files:** `scripts/autoapply_server.py` (`build_jobs_ready_response`), `extension/panel.html`/
`panel.js` (job-list view), `extension/background.js` (`OPEN_JOB` handler,
`chrome.tabs.create`+`sidePanel.setOptions`), `extension/manifest.json` (`"tabs"` permission),
`tests/test_autoapply_jobs_ready_endpoint.py` (new).

## 7 — Multi-session / per-tab state

Supports N parallel application sessions — one job/panel pair per tab — instead of the implicit
single "current match" every earlier increment assumed. Extension-only; every server handler is
already stateless per-request.

- `background.js`'s earlier separate `lastPlanByTab`/`pendingPageIdByTab` maps (both already
  tab-keyed) are unified into one `Map<tabId, {page_id, plan, lastFetchedAt}>`, read/written by
  every downstream handler via `sender.tab.id`.
- A **soft cap** (default 5, configurable in the extension's Settings page) applies to
  concurrently *launcher-opened* sessions only — organic `PLAN_REQUEST` scans from a hand-navigated
  tab are never gated, since capping those would regress increment 2's read-only overlay on every
  site. At the cap, opening another job from the launcher is **blocked with a message** in the
  panel rather than silently evicting an in-progress session.
- `chrome.tabs.onRemoved` clears a closed tab's session entry so it doesn't linger or count against
  the cap.

**Files:** `extension/background.js` (state map, cap, eviction), `extension/panel.js` (reads its
own tab's entry, shows the cap-reached message), `extension/options.html`/`options.js` (cap
setting). No Python file is touched by this increment.

**Risk carried forward:** the MV3 service worker's own lifecycle (Chrome can kill and restart it
at any time) means the state map isn't guaranteed to survive for the life of a long session — the
live-verification item in acceptance-criteria.md is the mitigation to actually exercise, not an
edge case to skip.

## 8 — Standalone native-messaging bridge auto-launch

Removes the standing manual step where a human opens a terminal, runs `python run.py --serve`, and
copy-pastes the printed token into the options page before the extension does anything. The
extension detects the bridge isn't running and starts it itself.

**Why this doesn't relitigate "never a daemon":** that decision is about *what* the process is (a
bridge holding Notion credentials and filesystem access, not a background service that outlives
the session), not about *who types the command*. Chrome only ever starts a native-messaging host
process in response to an explicit extension call (`chrome.runtime.sendNativeMessage`), fired only
from an explicit human gesture in this implementation — opening the side panel, or a bridge call
already triggered by something the human did — never an extension background timer, never
browser/OS startup. Only the keystrokes moved from a terminal to the extension UI.

**What genuinely changes:** today, a human reads a token off stdout and pastes it by hand — an
implicit confirmation that a *fresh* bridge process (this run's token) is the one paired to the
extension. After this increment, `host.py` reads `config/extension_token.txt` and hands it to the
extension automatically, closing that human-in-the-loop pairing step. Mitigated by: the token file
is still regenerated fresh per `--serve` invocation, still git-ignored, still loopback-only; the
manual paste flow in the options page remains available as a fallback, not removed.

- **`extension/native_host/host.py`** speaks Chrome's native-messaging wire protocol (a 4-byte
  little-endian length prefix + UTF-8 JSON on stdin/stdout; Chrome relaunches the host process per
  `connectNative()` call, so this is not a long-lived loop). On `{"action": "ensure_started",
  "port": N}`: checks `GET /health`; if down, spawns `python run.py --serve --port N` detached
  (`cwd` = repo root, resolved from `Path(__file__).parents[2]`), stdout/stderr redirected away
  from the host's own stdio (must not pollute the wire-protocol channel); polls `/health` up to
  ~8s; on success reads `config/extension_token.txt` (the same `TOKEN_PATH` increment 0 writes)
  and responds `{status, port, token}`; on timeout or any exception, responds `{"status": "error",
  "message": ...}` — never raises past the wire-protocol write.
- **`com.careerpilot.bridge_host.json`** (manifest template) + **`run_host.bat`** (one-line
  wrapper — Chrome's native-messaging `path` must be directly executable, and a bare `.py` has no
  reliable file association across machines).
- **`scripts/install_native_host.py --extension-id <id>`** (the id is copied from
  `chrome://extensions` after loading the unpacked extension once — undiscoverable otherwise,
  since an unpacked extension's id is only assigned at load time): fills the manifest template's
  absolute paths, writes a resolved, machine-specific copy
  (`extension/native_host/com.careerpilot.bridge_host.installed.json`, git-ignored), then
  registers it — Windows: sets the default value of
  `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.careerpilot.bridge_host` (and the Edge
  hive); POSIX: copies the manifest into the OS-specific native-messaging-hosts directory (written,
  **not independently verified** — no POSIX Chrome install available in this environment). Idempotent
  — re-running with a new `--extension-id` overwrites cleanly.
- **`extension/background.js`**: wraps `bridgeFetch`/`bridgeFetchBinary` — on a `status: 0` result
  (nothing answered at all, not an HTTP error), calls `ensureBridgeRunning()`, which sends the
  native message, stores the returned token/port via `chrome.storage.local.set`, and retries the
  original request **exactly once** (never loops; a second failure surfaces exactly as it would
  have before this increment existed). `chrome.runtime.lastError` (host not registered) surfaces a
  distinct `"native-host-missing"` reason rather than the generic unreachable message.
- **`extension/panel.js`/`options.html`**: a small state machine replacing the two hardcoded
  "is `python run.py --serve` running?" strings — `checking → starting → connected` /
  `native-host-missing` (points at the install step) / the original manual copy-paste flow, kept
  working as-is for anyone who hasn't run the installer or is on an unregistered platform.

**Files:** `extension/native_host/host.py`, `extension/native_host/run_host.bat`,
`extension/native_host/com.careerpilot.bridge_host.json` (new); `scripts/install_native_host.py`
(new); `tests/test_native_host.py` (new); `extension/manifest.json` (`"nativeMessaging"`
permission); `extension/background.js` (`ensureBridgeRunning()`); `extension/panel.js`/
`options.html` (status state machine); `.gitignore`
(`extension/native_host/com.careerpilot.bridge_host.installed.json`).

**Risk carried forward:** native-messaging registration is finicky in practice — exact
`allowed_origins` match, manifest file permissions, registry hive mismatches between
Chrome/Chromium/Edge builds. Expect the native-host-missing fallback path to be exercised more
than the happy path during initial rollout.

## Files touched (final map)

**Python:** `scripts/autoapply_server.py` (the whole bridge — `/health`, `/plan`, `/jobs/ready`,
`/resume/meta`, `/resume`, `/drafts`, `/confirm-applied`), `scripts/install_native_host.py`,
`run.py` (`--serve`/`--port`), `scripts/autoapply_browser.py` (`accepts_docx()` extraction only).

**Extension:** `extension/manifest.json`, `extension/background.js`, `extension/content.js`,
`extension/drafts.js`, `extension/panel.html`, `extension/panel.js`, `extension/options.html`,
`extension/options.js`, `extension/overlay.css`, `extension/native_host/host.py`,
`extension/native_host/run_host.bat`, `extension/native_host/com.careerpilot.bridge_host.json`.

**Tests:** `tests/test_autoapply_server.py`, `tests/test_run_serve_wiring.py`,
`tests/test_autoapply_job_match.py`, `tests/test_autoapply_jobs_ready_endpoint.py`,
`tests/test_autoapply_drafts_endpoint.py`, `tests/test_autoapply_applied_confirmation.py`,
`tests/test_native_host.py`, `tests/test_autoapply_notion.py` (extended grep parametrization).

**Docs:** this feature's `spec/` files; `CLAUDE.md` (new "Layer 3 — browser extension" subsection
under Stage 7, plus the reformulated `Applied`-invariant paragraph); `docs/CHANGELOG.md` (Step 15
entry).

## Other risks (beyond the per-increment "carried forward" notes above)

1. **`isTrusted: false`** — some ATS validators and dropzones reject synthetic events; nothing a
   content script can do. Expect a nonzero per-site failure rate. Mitigated by the tier-3 copy-path
   fallback and verify-don't-claim (increment 3a) — an unfilled field stays visibly unfilled rather
   than silently wrong.
2. **Workday stays largely unsolved** — see problem.md.
3. **Maintenance** — a second UI in a language this repo has no test runner for.
4. **Mild SSRF shape** in `_download_tailored_resume()` (`autoapply.py:493`) now that a browser
   request can trigger it — closed by constraining the fetch host to `raw.githubusercontent.com`
   (increment 3a).
