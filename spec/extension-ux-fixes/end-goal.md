# End goal

Once this ships, using the extension day to day should feel unremarkable:

- A stale bridge token recovers itself transparently — no manual re-paste, ever, for an ordinary
  bridge restart.
- Badges on a live application form are visually stable. They only change when the underlying
  field's status actually changes; they don't flicker during normal page activity.
- Clicking a job in the panel's job list always lands you on that job's plan in the new tab — never
  silently back on the job list, and never a stuck/ambiguous loading state.
- Each open job tab is independently correct — two jobs open in two tabs never bleed state into
  each other.

Scope stays exactly what it is today (scan the live DOM, propose a plan, fill only on explicit
click) — this story is about the existing UI being trustworthy, not about doing more.
