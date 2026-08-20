# Acceptance criteria

## Bridge scaffold (increment 0)
- [x] `GET /health` returns 200 with no token; every other path 404s until its route exists.
- [x] A wrong/missing token against an authed route is rejected.
- [x] The bind literal is `"127.0.0.1"`, never all interfaces.
- [x] Starting `--serve` twice on the same port fails cleanly.
- [x] The token file's content differs across two separate `--serve` invocations.

## Plan + identify + resume/meta (increment 1)
- [x] A `page_id`-carrying request short-circuits to rung 0 without touching the candidate pool.
- [x] A `SAMPLE_QUESTIONS`-equivalent DOM payload yields a field-for-field identical plan to the
      CLI path.
- [x] LinkedIn/Indeed URLs → every field `review_required`, enforced server-side.
- [x] Each identify rung (exact URL, normalized URL, Greenhouse `?gh_jid=`, two-match `ambiguous`,
      no-match `resume-missing`) is covered; a row at `Application Queued` still matches.
- [x] `/plan` writes no status to any Notion page. `/resume/meta` returns metadata with no bytes,
      even on a read-only channel.

## Side-panel shell + read-only overlay (increment 2)
- [x] `content.js`/`panel.js` contain no submit-token, no `confirm-applied`, no `applied`, no
      `draft` reference (grep-enforced, scope-creep guard for later increments).
- [ ] **Live:** badges match what `/plan` returns for the same DOM; the panel names the right
      role/filename; normalization is exercised end-to-end (`?gh_src=test`, `job-boards.` host); an
      untracked job shows "no match" with no filename offered; LinkedIn/Indeed badge everything
      `review_required` read-only; nothing on the page is modified; the auth header never
      originates from `content.js`'s execution context.

## Resume attach (increment 3a — go/no-go checkpoint)
- [x] `/resume` bytes 403 on a read-only channel while `/resume/meta` stays allowed.
- [x] A path outside `RESUMES_DIR` is refused; a bad token is rejected before any Notion read.
- [x] A PDF-only form gets a converted PDF; the download fetch host is constrained.
- [ ] **Live:** attach readback succeeds (or the Copy-path fallback appears) across Greenhouse,
      Ashby, a custom careers page reached through a LinkedIn posting, and Workday; an untracked
      job's resume field badges `resume-missing` with no attach attempted; LinkedIn Easy Apply 403s
      bytes but still renders filename + Copy path.

## Field fill on click (increment 3b)
- [ ] **Live:** clicking Fill fills every `ready` field with the same value the CLI would produce;
      nothing is filled before the click; a `review_required` field (including a drafted-but-not-
      inserted essay) is never filled by this button; no network POST leaves the page until the
      human clicks the form's own Submit.

## Interactive drafts (increment 4)
- [x] A drafted field is never `ready` after `/drafts` runs — only a `draft` key is added.
- [x] An unmatched `page_id` returns 404 with no draft; `AUTOAPPLY_DRAFT_ESSAYS=False` → clean 404.
- [ ] **Live:** the draft panel shows one AI-drafted answer per free-text question; editing before
      Insert works; Insert writes exactly that text and re-badges it; `content.js` contains no
      `draft` token at all (permanent, not just increment-scoped).

## Confirm-applied (increment 5)
- [x] `HUMAN_CONFIRMED_STATUS`/`CONFIRMABLE_STATUSES` are disjoint from `WRITABLE_STATUSES`.
- [x] Missing `confirmed_by` → 400, zero writes attempted; a list/batch `page_id` → rejected, zero
      writes.
- [x] Happy path sets `Applied` + `Date Applied` + an `Application Log` line containing
      "human-confirmed via extension" on exactly one page, leaving other pages untouched.
- [x] A Notion-dropped status is reported as a failure, not a silent 200.
- [ ] **Live:** confirming a job actually submitted shows `Applied`/`Date Applied`/audit line in
      Notion; the Confirm button is disabled/absent when no `page_id` is resolved.

## Job list + launcher (increment 6)
- [x] `GET /jobs/ready` returns rows matching `db_get_ready_to_apply()`'s contract and makes no
      Notion writes.
- [ ] **Live:** clicking a row opens that job's URL in a new tab and the panel immediately shows
      that job's plan, no candidate-list/ask step; a job whose URL 404s still leaves the panel
      showing the correct plan.

## Multi-session / per-tab state (increment 7)
- [ ] **Live:** two jobs opened from the launcher in two tabs show independent plans; actions in
      one tab's panel have no effect on the other's session; closing one tracked tab leaves the
      other's session intact; opening past the soft cap shows a blocked-with-message state; a
      service-worker restart mid-session doesn't corrupt `page_id` association.

## Native-messaging auto-launch (increment 8)
- [x] `ensure_started` against a mocked-healthy `/health` returns `already_running` without
      spawning; against mocked-unreachable, spawns exactly once and returns `started` with the
      token read from a fixture; a poll that never turns healthy returns a bounded error, never
      hangs; any exception in the spawn/poll path is caught, never unhandled.
- [ ] **Live (Windows verified; POSIX registration written but not independently verified — a
      known residual gap):** fresh state → opening the panel shows checking → starting → connected
      with no manual step; an already-running bridge shows connected with no duplicate spawn;
      native host not installed → native-host-missing state with a working link, manual fallback
      still functions; killing the bridge mid-session causes re-detect/restart/recovery without a
      page reload.

## Story close-out (outstanding)
- [ ] Install and live-test the native-messaging host — nothing about it has touched a real Chrome
      instance yet.
- [ ] Run through increments 3b, 4, 5, and 7's live checklists above in an actual browser session.
- [ ] Commit the working-tree changes.
