# Plan

## Bug 1 — token requires manual re-paste

**Root cause (confirmed):** `extension/native_host/host.py`'s `ensure_started()` only returns the
token on the fresh-spawn branch; the `already_running` branch (bridge already answering
`/health`) returns `{"status": "already_running"}` with no token. Separately,
`extension/background.js`'s `bridgeFetch`/`bridgeFetchBinary` (`:69-81`, `:111-120`) only call
`ensureBridgeRunning()` — which is what triggers native messaging — on `status === 0` (nothing
listening). A stale token produces an ordinary `401`, returned straight through with no retry.

**Fix:**
- `extension/native_host/host.py`, `ensure_started()`: in the `already_running` branch, also
  `read_token()` and include it in the response, wrapped in its own `try/except OSError` so a
  momentarily-unreadable token file still degrades to today's `{"status": "already_running"}`
  rather than turning a healthy bridge into an error response. Update the module docstring's
  response-shape note to match.
- `extension/background.js`: broaden the retry condition in both `bridgeFetch` and
  `bridgeFetchBinary` from `result.status !== 0` to `result.status !== 0 && result.status !== 401`,
  so a `401` also triggers `ensureBridgeRunning()` → fresh token via native messaging →
  `chrome.storage.local.bridgeToken` updated → one retry. Update the comment above `bridgeFetch`.
- `tests/test_native_host.py`: update `test_ensure_started_already_healthy_does_not_spawn` (today
  asserts the response is exactly `{"status": "already_running"}`) to expect a `token` key, and add
  a case for the token-file-missing fallback (still `{"status": "already_running"}`, no exception).

## Bug 2 — badge flicker

**Root cause (confirmed):** `extension/content.js`'s `paintBadges()` (`:235-244`) unconditionally
does `document.querySelectorAll(".cpai-badge, .cpai-attach").forEach(b => b.remove())` and
rebuilds every badge from scratch on every call. `runScan()` calls it after every debounced
`MutationObserver` firing (800ms trailing debounce, `:415-421`), and inserting/removing badges is
itself a DOM mutation that can re-arm that same observer — on SPA-heavy ATS pages
(Greenhouse/Ashby/Workday, which re-render constantly on their own) this produces a near-continuous
remove+rebuild cycle. There is debouncing but no diffing against what's already painted.

**Fix (`extension/content.js`):**
- Add a module-scoped `paintedFields` Map (`field.name -> {signature, node}`), sibling to the
  existing `filledFieldNames`/`insertedFieldNames`. Compute a cheap signature per field
  (`status|type|source`). In `paintBadges()`, skip touching a field's DOM entirely when its
  signature is unchanged and its badge node is still connected and correctly anchored right after
  its field; only remove+reinsert badges whose signature actually changed, and remove badges for
  fields that dropped out of the plan.
- Tighten the `MutationObserver` callback to ignore mutations whose added/removed nodes are all
  the extension's own UI (`.cpai-badge`, `.cpai-attach`, `#cpai-fill-btn`), so painting the
  extension's own badges doesn't re-arm its own scan — belt-and-suspenders with the diff above,
  targeting the exact "insertion mutates DOM → observer fires → re-scan → re-insert" loop already
  flagged in an existing code comment (`:99-102`).

## Bug 3 — job-open still shows job list

**Root cause (confirmed):** `background.js`'s `OPEN_JOB` handler correctly calls
`chrome.sidePanel.setOptions({tabId, path: "panel.html?page_id=..."})` — the right MV3 per-tab
API — but `panel.js` never reads `page_id` from `location.search` anywhere; it's dead code. The
panel's only refresh path is a 2s poll of `GET_LAST_PLAN`, which resolves the session via
`chrome.tabs.query({active: true, currentWindow: true})` — whatever tab is active at that poll
tick, not necessarily the newly opened one. `render()` falls back to `loadJobList()` whenever the
resolved plan is falsy, which is also true momentarily by design (`session.plan` starts `null`
until `content.js`'s own scan completes on the new tab).

**Fix:**
- `background.js`: in `OPEN_JOB`, add a non-consumed `openedPageId` alongside the existing
  consume-once `pageId` on the session object (`PLAN_REQUEST`'s handler already nulls `pageId`
  after first use). Extend `GET_LAST_PLAN` to accept an optional `pageId` in the message and, when
  present, resolve by scanning `sessionByTab` for a matching `openedPageId` instead of the
  active-tab query — return `{notFound: true}` if no session matches (tab closed) or
  `{pending: true}` if the session exists but `plan` hasn't arrived yet. The existing no-`pageId`
  path (toolbar-opened panel on the active tab) is unchanged.
- `panel.js`: read `page_id` from `location.search` once at load, pass it through `refresh()`'s
  `GET_LAST_PLAN` message. In `render()`, when a `launchedPageId` is present, branch before the
  existing `!planResult -> loadJobList()` fallback: show a "Loading this job's application form…"
  state on `pending`/falsy, a "tab was closed" state on `notFound`, otherwise render the plan as
  today. The existing `setInterval(refresh, 2000)` loop is unchanged — it surfaces the resolved
  plan within 2s once `content.js`'s scan completes.

## Tab isolation — verify, don't build

After bug 3 lands: open two different jobs from the list into two tabs, confirm each tab's side
panel shows only its own job. If state still bleeds across tabs after that, that's a new finding
to investigate on its own — not a reason to pre-build a `chrome.tabGroups` layer now.

## Files

- **Modify:** `extension/native_host/host.py` — `ensure_started()` token-on-already-running fix
- **Modify:** `extension/background.js` — `bridgeFetch`/`bridgeFetchBinary` 401 retry;
  `OPEN_JOB`/`GET_LAST_PLAN` `openedPageId`/`pageId`-keyed lookup
- **Modify:** `extension/content.js` — diff-based `paintBadges()`, own-mutation filter on the
  `MutationObserver`
- **Modify:** `extension/panel.js` — read `page_id` from `location.search`, loading/not-found
  states in `render()`
- **Modify:** `tests/test_native_host.py` — update one existing test, add one new case
- **No change:** Notion schema, `config/settings.py`, security model (127.0.0.1-only binding,
  per-`--serve`-start random token, CORS-echoes-Origin), never-submit invariant
