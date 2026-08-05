# Verification

**Automated:** `pytest -v` (Python side, all increments) plus the grep-based JS contract tests in
`tests/test_autoapply_notion.py` (no submit-token, no `confirm-applied`/`applied`/`draft` leakage
into `content.js`; `panel.js` allowed the plain "applied" word only). Per-increment automated
assertions are listed in the "Verified (automated)" checkmarks in acceptance-criteria.md; the
concrete live-session scripts for the still-open items are embedded per increment in plan.md
(what to click, what to observe) — acceptance-criteria.md's unchecked boxes are the index of what
still needs running.

**Remaining before this story can close:**
1. Install and live-test the native-messaging host (increment 8) — nothing about it has touched a
   real Chrome instance yet.
2. Run through increments 3b, 4, 5, and 7's live checklists (see plan.md / acceptance-criteria.md)
   in an actual browser session.
3. Commit the working-tree changes (currently uncommitted).

Once those pass, flip `meta.md`'s Status from `in-progress` to `done` and clear the checked-off
items above.
