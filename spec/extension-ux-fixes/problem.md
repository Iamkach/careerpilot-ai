# Problem

Using the Layer 3 extension (`extension/` + `python run.py --serve`) day to day surfaced three
concrete bugs:

1. **Token has to be manually re-pasted every session.** Any time the bridge is restarted
   independently of the exact native-messaging spawn (e.g. a manual `python run.py --serve` —
   the documented fallback in `options.html`), the extension keeps using its old, now-stale
   token and never recovers on its own.
2. **Field badges flicker roughly every second** on a live application form — visually
   uncomfortable, not just cosmetic.
3. **Clicking a job in the panel's job list still shows the job list** in the newly opened tab's
   side panel, instead of switching to that job's plan/info.

The user also raised wanting "each tab to have its own memory/context, not shared across tabs"
and wanting the extension to "read through the browser and perform actions." Investigation found
the per-tab data model (`sessionByTab`, a `Map` keyed by `tabId`) already exists and already
isolates state correctly — the "shared context" symptom is very likely just bug 3 showing through,
not a missing isolation layer. "Read through the browser and perform actions" is already
`content.js`'s job (scan → build plan → fill on explicit click) and stays exactly that scope here:
the never-submit invariant is unchanged by this story — Stage 7 has no submit code path anywhere,
`extension/` included, and this story does not add one.
