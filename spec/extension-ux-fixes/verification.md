# Verification

**Automated:** `pytest tests/test_native_host.py` after updating it; `pytest -v` for the rest of
the suite as a regression check (server-side auth/health logic is untouched, so
`tests/test_autoapply_server.py` / `tests/test_autoapply_jobs_ready_endpoint.py` should stay green
with no edits needed).

**Manual, real `load-unpacked` Chrome session against a live Greenhouse job:**
1. *Token:* start the bridge manually (`python run.py --serve`), confirm it works, then set a
   deliberately wrong `chrome.storage.local.bridgeToken` via the extension's devtools console and
   trigger a bridge call — expect a transparent one-time recovery (no manual re-paste), visible as
   a single 401-then-retry in the service-worker console, not a loop.
2. *Flicker:* open a form, let it scan/paint, then watch 30-60s without interacting — badges
   should stay visually stable; confirm via DevTools that unchanged fields aren't being
   removed/reinserted every debounce cycle. Click "Fill N ready fields" and confirm filled badges
   don't revert.
3. *Job routing:* click a job from the panel's job list, confirm the new tab's panel shows a
   brief loading state then that job's plan (never falls back to the list); open two jobs into two
   tabs and confirm each panel shows only its own tab's job; close a launched tab and confirm the
   "tab was closed" message rather than a stuck loading state or silent list fallback.
