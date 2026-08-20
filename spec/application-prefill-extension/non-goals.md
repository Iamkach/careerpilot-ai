# Non-goals

- **Backlog drainage.** The 450 existing actionable tracker rows are explicitly out of scope — this
  is for new inbound jobs only.
- **Fully unattended/hands-off applying.** The extension is interactive only; it does nothing for
  an unattended run and complements the Playwright layer rather than replacing it.
- **Per-ATS account creation and email verification** (Workday tenants). Being logged in helps, but
  the tenant account must already exist — do not gate this project on solving that.
- **ATS token/board write-back from the job launcher.** Deferred to `spec/board-token-harvesting/`
  — the launcher stays read-only on that front.
- **A general `POST /status` route.** Considered while folding in the docked side-panel launcher
  proposal; not adopted. `POST /confirm-applied` remains the only status write the extension makes,
  deliberately narrower than a general status-setting endpoint would be.
- **Ashby in `FILLABLE_CHANNELS`** (the Playwright/Layer-2 route). This extension covers Ashby
  interactively with no per-ATS schema or selector work, which is this story's scope — it is **not**
  covered for an unattended nightly run. Revive the per-ATS Playwright adapter idea only if
  hands-off applying becomes a goal.
- **A JS unit test runner.** Keep the JS thin; rely on grep + Python contract tests. If
  `content.js` starts needing unit tests, logic has leaked out of Python and should be pushed back.
- **Chrome Web Store distribution.** Unpacked/developer-mode only — a store listing for something
  that reads application forms is a different review problem, not attempted here.
