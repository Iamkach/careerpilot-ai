# Non-goals

- **Building a real `chrome.tabGroups` layer.** `sessionByTab` (`background.js:130`) is already a
  genuine per-`tabId` `Map` with cleanup on `chrome.tabs.onRemoved`. Don't build a browser-tab-group
  layer speculatively — verify per-tab isolation after fixing bug 3 (open two jobs into two tabs,
  confirm each panel shows only its own job) before considering it further. If state still bleeds
  across tabs after that, that's a new finding to investigate on its own, not a reason to pre-build
  this now.
- **A new content.js → panel.js message type** for job-open routing. The fix is UI state
  (loading / not-found / plan, keyed off `page_id`), not a new push mechanism.
- **Broadening what the extension automates.** No submit code path is added anywhere — that
  invariant is unchanged by this story.
