# Step 15i — Multi-session / per-tab state (Layer 3, increment 7)

**Status:** queued, not started (2026-07-31). Size **S**. Depends on
[step-15h](step-15h-job-list-launcher.md). Ninth and last of nine sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first). Folded 2026-07-31 from
`docs/refinement-plans/auto-apply/step-15-interactive-launcher.md` — flagged there as the one
item in the whole launcher delta most likely to need iteration once built; treat this story's
design as a first cut, not a final shape.

## Goal

Support N parallel application sessions — one job/panel pair per tab — instead of the implicit
single "current match" every earlier story assumed.

## Scope

**In:** `background.js`'s per-tab state map; scoping every downstream call
(`/plan`, `/drafts`, `/resume`, `/resume/meta`, `/confirm-applied`) by the initiating tab; a soft
cap on simultaneously-tracked tabs; eviction on tab close.

**Out:** any change to `autoapply_server.py` or any other Python file — every handler is already
stateless per-request (`page_id`/DOM payload in, response out), so this story is extension-only.
No general `POST /status` route (not adopted, see `step-15h`).

## Implementation

### Per-tab state map

Replace `step-15b`–`step-15g`'s implicit single-current-match variable in `background.js` with
`Map<tabId, {page_id, plan, lastFetchedAt, ...}>`. Every message from `content.js`/`panel.js` to
`background.js` carries (or `background.js` derives from `sender.tab.id`) the tab id, and every
outbound fetch to the bridge is scoped to that tab's entry — not "whatever the panel most recently
showed."

### Soft cap on concurrent sessions

`AUTOAPPLY_DAILY_CAP` (Python-side, default 10) bounds daily application *volume*; it does not
bound concurrently *open* sessions, and the two are orthogonal — this cap exists purely to keep
`background.js`'s map and the panel's own session-switcher UI bounded and readable, not as a
Notion-side enforcement mechanism. Default 5, configurable via the options page (`step-15c`).
Behavior at the cap is a per-implementation choice to make and document in this story's PR: either
evict the oldest untouched session or block opening a new one with a message in the panel — pick
one, note the choice, and cover it in the live verification below.

### Eviction

Listen for `chrome.tabs.onRemoved` and drop that tab's map entry — a closed tab's in-memory plan
shouldn't linger and shouldn't count against the soft cap.

## Reused verbatim

`autoapply_server.py`'s existing stateless handlers (`/plan`, `/drafts`, `/resume`,
`/resume/meta`, `/confirm-applied`) — untouched. No Python file is modified by this story.

## Files

**Modified:** `extension/background.js` (state map, cap, eviction) · `extension/panel.js` (reads
its own tab's entry rather than a shared global) · `extension/options.html`/`options.js` (cap
setting).

## Verification

Live only — this story has no Python surface and therefore no new pytest coverage:
1. Open two jobs from the launcher (`step-15h`) in two different tabs of the same window; each
   tab's panel shows that tab's own plan, independently.
2. Fill/draft/confirm actions in one tab's panel have no effect on the other tab's session or plan.
3. Closing one tracked tab leaves the other's session fully intact.
4. Opening a session past the soft cap behaves as documented in this story's PR (eviction or
   block-with-message) — not silently ignored and not a crash.
5. Reloading the extension (service worker restart) doesn't corrupt an in-progress session's
   `page_id` association — re-derive from `sidePanel`'s per-tab path/state if the in-memory map is
   lost, rather than silently showing a stale or wrong plan.

## Risks

Flagged by the launcher plan as the one genuinely new *design* in the whole delta — everything
else was reuse or a small extension of existing endpoints. The MV3 service worker's own lifecycle
(it can be killed and restarted by Chrome at any time) means the state map is not guaranteed to
survive for the life of a long application session; verification item 5 above is the mitigation
to build and test explicitly, not an edge case to skip.

## Docs close-out (epic-level, lands with this story)

Per the epic's "Docs lifecycle" section: add a "Layer 3 — browser extension" subsection under
Stage 7 in the root `CLAUDE.md`, and reformulate the `Never Applied` paragraph there (`:339-343`)
to match the invariant `step-15g` restates. Add a Step 15 entry to `docs/CHANGELOG.md`, and a
backfilled Step 10 entry if cheap (it currently has none).
