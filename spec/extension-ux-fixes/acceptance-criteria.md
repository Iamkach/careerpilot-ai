# Acceptance criteria

- [ ] A stale bridge token (401 response) triggers exactly one automatic recovery via native
      messaging — no manual re-paste, and no retry loop.
- [ ] Unchanged fields on a live application form are not removed/reinserted on every debounced
      scan cycle; badges stay visually stable over 30-60s of no user interaction.
- [ ] A filled or inserted badge never reverts to its pre-fill/pre-insert state during a scan.
- [ ] Clicking a job in the panel's job list shows a loading state in the new tab, then that job's
      plan — never a silent fallback to the job list.
- [ ] Two jobs opened into two different tabs each show only their own job's plan in their own
      panel.
- [ ] Closing a launched tab surfaces a "tab was closed" message, not a stuck loading state or
      silent list fallback.
