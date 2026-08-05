# Constraints

1. **No `chrome.tabGroups` dependency.** See non-goals — verify existing per-tab isolation before
   ever adding a real tab-group layer.
2. **Token recovery stays "never loop, one retry"** — same contract `bridgeFetch` already uses for
   `status === 0`; broadening the trigger to include `401` does not change that contract.
3. **Badge diffing must not touch the direct-mutation fill/insert paths.** `markFilled()` and the
   `CPAI_INSERT_FIELD_VALUE` handler mutate a badge node in place and never call `paintBadges()` —
   the new skip-when-unchanged logic in `paintBadges()` can only leave those nodes alone, never
   overwrite them.
4. **Job-open routing fix is UI-state, not a new push mechanism.** Panel shows an explicit
   "loading"/"tab was closed" state keyed off `page_id` instead of silently falling back to the
   job list.
