# Runtime Notes — outstanding ops/infra items

Open issues that live in **GitHub repo settings, secrets, or integrations** — not in this
repo's code. Nothing here blocks local development; `docs/TODO.md` is reserved for code and
development-blocking work. See `docs/GITHUB_ACTIONS_SETUP.md` for the setup instructions these
notes assume.

- **`tests.yml` CI gate has never actually run.** Last checked 2026-07-19 (PR #11 review):
  every Actions run showed `startup_failure` at 0s with no job name, on both the
  `pull_request` and `push` triggers. Both workflow files parse fine and the suite is green
  locally (`pytest -v`), so this is environmental, not a code defect — most likely Actions
  disabled for the repo, or a spending/billing limit on the private repo.
  **Needs a human with repo Settings access:** check Settings → Actions and the billing page.
  Until resolved, "CI gate on every PR/push" is a claim the repo doesn't actually hold up.
- **Stale Supabase Preview integration still reporting on PRs.** Vestigial now that
  `sync_notion_to_supabase()` is a no-op (Notion is the store). Decide whether to remove it
  from the repo's integrations — needs the same Settings access as above.
- **`nightly-pipeline.yml` is missing two repo secrets.** `NOTION_DB_ID` and
  `APIFY_API_TOKEN` aren't in the workflow's `env:` block, so a scheduled run currently points
  at an empty `NOTION_DB_ID` and can't use Apify sources. Add both as repo secrets
  (Settings → Secrets and variables → Actions) and wire them into the `env:` block the same way
  `NOTION_API_KEY` already is. Surfaced 2026-07-22 during Step 11 (forkable setup) work.
- **`CLAUDE_CODE_OAUTH_TOKEN` expires periodically.** If a scheduled run fails on subscription
  auth, re-mint it locally with `claude setup-token` (requires Claude Pro/Max) and update the
  repo secret — this is a token-rotation task, not a bug.
