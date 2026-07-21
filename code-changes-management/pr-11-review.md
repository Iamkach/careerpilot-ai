# PR #11 — Full Review (103 files, +12,176 / −1,930)

> **Catch up main: pipeline rewrite, multi-source sourcing, test suite**
> Base: `main` ← Head: `feature/god-speed`
> Author: Krishna Achyuth (`Iamkach`)
> PR: https://github.com/Iamkach/careerpilot-ai/pull/11
> State: **OPEN** · Latest reviewed commit: `acdf194` (via `gh pr diff 11`)

This is the full-diff follow-up review (previous pass covered 10 of 99 files and is
superseded by this one). CI status: `pytest` green in ~27s on the latest push — the
earlier `startup_failure` seen on this workflow was a transient GitHub Actions issue,
not a config problem, and is **not** tracked as an open item.

**2026-07-21 update — /review pass, re-verified against `gh pr diff 11`:** items #1 and
#2 below (`render_docx.py` run-flattening, and all three stage 2/3 cross-assignment
paths) were fixed and merged via PR #12 (`fix/pr-11-review-blockers` →
`feature/god-speed`, commits `ee524c4`/`acdf194`) before this pass ran. Marked
**RESOLVED** in place rather than removed, so the history of what was found and fixed
stays visible. Note for future passes: verify findings against `gh pr diff <n>` /
`gh api .../contents/<path>?ref=<branch>` directly — the first attempt at this
re-verification mistakenly read a stale local checkout on an unrelated branch
(`feature/step-10-auto-apply`) and almost re-reported both as still open.

---

## 1. Blocking — ✅ RESOLVED (PR #12, `ee524c4`)

### ~~🔴 Silent formatting corruption in delivered resumes~~ — `scripts/render_docx.py:132`

`_replace_para_text()` collapsed every run in a paragraph into `runs[0]`, so the whole
line inherited the first run's formatting. Reproduced against the actual
`Achyuth_Resume.docx`:

```
BEFORE:  'Languages & Frameworks: '                    bold=True
         'Java, Python, JavaScript, TypeScript, ...'   bold=None
AFTER:   'Languages & Frameworks: Java, Python, ...'   bold=True   ← entire line
```

Not theoretical — the resume has 12 mixed-formatting paragraphs, and they were exactly
what stage 2's prompt targets (priority #3: "TECHNICAL SKILLS: append missing keywords
to existing lines"). All four skills lines are bold-label + normal-list; the three
experience headers (bold title | normal company | italic dates) were equally exposed.

**Fix landed:** `_replace_para_text()` now finds the run(s) overlapping the matched span
and splices only within them, preserving every other run's formatting untouched —
confirmed on `feature/god-speed`. The old
`test_characterization_run_collapsing_loses_formatting_on_rest_of_paragraph` test (which
locked in the buggy behavior on purpose) was replaced with
`test_apply_docx_edits_preserves_bold_run_on_mid_run_edit` and
`test_apply_docx_edits_preserves_formatting_when_edit_spans_run_boundary`, asserting the
new correct behavior.

**Item #10 (double-edit-in-one-paragraph clobber) also fixed**, on branch
`fix/pr11-issue10-same-paragraph-double-edit-clobber`: `apply_docx_edits()` now snapshots
every paragraph's original text once up front and resolves each edit's match position
against that fixed snapshot, instead of re-scanning the paragraph's live (possibly
already-edited) text edit-by-edit. Edits sharing a paragraph are grouped, sorted by their
original-text position, and spliced into the paragraph's original run layout in one pass
via the new `_apply_para_edits()` (generalizing `_replace_para_text()`, which is now a
thin single-span wrapper around it) — so a later edit's `old` match can never be thrown
off by an earlier edit's `new` text, and formatting is preserved exactly as PR #12 left
it. A genuine overlap between two edits' spans in the original text (no correct
simultaneous resolution) is reported via `unmatched` rather than corrupting the
paragraph. The old `test_characterization_same_paragraph_double_edit_clobber` test (which
locked in the buggy behavior on purpose) was replaced with
`test_apply_docx_edits_sequential_same_paragraph_edits_dont_clobber` plus three more
covering reversed edit order, an earlier edit shifting text length before a later one,
and genuinely overlapping spans.

---

## 2. Cross-assignment — ✅ RESOLVED (PR #12, `ee524c4`)

Three independent paths, all silent, all in the "output looks plausible" direction —
none had test coverage at the time they were found.

1. **`scripts/stage2_tailor.py:280`** — same-company collision. `by_company` was keyed
   on lowercased company name. Two `Reviewed` roles at one company (a normal outcome of
   a real job search) → the second overwrote the first, and if `by_index` missed, a job
   got *another role's* resume edits — saved and marked `Resume Tailored`.
2. **`scripts/stage3_outreach.py:96`** — positional alignment.
   `entry = data[i] if i < len(data) else {}` ignored the `company` field the model
   returns. One omitted or reordered entry shifted every subsequent company mapping,
   while the saved file's header still showed the *correct* company (it came from the
   loop var, not the model output) — masking the mismatch.
3. **`scripts/stage3_outreach.py:183`** — same collision pattern as #1:
   `email_by_company` re-keyed by company, so two roles at one employer both got the
   second role's email.

**Fix landed:** all three now key primarily off `job_index`/`company` field validated
against the batch's own `company_counts`, falling back to the company-keyed lookup
*only* when that company is unique in the batch — otherwise the entry is treated as
unresolved and routed to the existing per-job fallback path instead of a silent
misassignment. Confirmed on `feature/god-speed`.

---

## 3. Two nightly workflow modes are broken by construction — ⏳ STILL OPEN

Re-confirmed against `feature/god-speed` in the 2026-07-21 pass — not touched by PR #12.

`nightly-pipeline.yml` offers `stage3` and `stage5` as `workflow_dispatch` modes, but:

- `run.py:158` `stage3()` doesn't pass `no_confirm`, so `stage3_outreach.py:175,199`
  calls `input()`. Only `--evaluate` passes it through today (`run.py:253`).
- `stage5_interview_prep.py:144,149` calls `input()` unconditionally.

In Actions, stdin is `/dev/null` → `EOFError` → job fails every time it's invoked.

**Fix:** either thread `no_confirm` through `--stage 3` (and add a non-interactive path
for stage 5), or drop those two modes from the workflow's dispatch options until they're
non-interactive.

---

## 4. Worth fixing — ✅ ALL RESOLVED (2026-07-21, PRs #13–#18, merged to `feature/god-speed`)

Items #6–#11 were fixed in six independent branches off `feature/god-speed`, each with
its own test coverage, then merged in dependency order (batched verify first, since the
zero-edit gate touches the same `run()` loop it restructures):

- ~~**#6 — `stage2_tailor.py:422`** — status advances to `Resume Tailored` even when
  `edits` is empty.~~ ✅ Fixed (PR #13, `fix/pr11-issue6-zero-edit-status`). A zero-edit
  job is now left in `Human Review` with a guidance note instead of `Resume Tailored`,
  mirroring `_sponsorship_gate()`'s pattern. (Rebasing this onto PR #18's batched-verify
  restructuring surfaced a real bug: the zero-edit check was reading a stale `edits`
  variable left over from a different loop phase due to Python's loop-scoping, gating
  every job in a run on one arbitrary job's edit count. Fixed by threading `edits`
  through the `tailored` tuple so each job's own value is used.)
- ~~**#7 — `python-docx` is undeclared.**~~ ✅ Fixed (PR #15,
  `fix/pr11-issue7-python-docx-dependency`). `requirements.txt` now lists `python-docx`;
  `docxtpl` confirmed unused in any active path and removed. Also fixed #14 (stale
  module docstring) in the same PR.
- ~~**#8 — `stage2_tailor.py:94`** `fetch_jd()` strips tags without removing
  `<script>`/`<style>` first.~~ ✅ Fixed (PR #14,
  `fix/pr11-issue8-fetch-jd-strip-script-style`). `fetch_jd()` now reuses
  `sources._strip_html()` instead of a second, weaker inline regex.
- ~~**#9 — `verify_tailored_score()`** issues one AI call per job.~~ ✅ Fixed (PR #18,
  `fix/pr11-issue9-batch-verify-tailored-score`). New `verify_tailored_scores_batch()`
  mirrors `tailor_resumes_batch()`'s batching pattern (one call, chunked at 20 jobs,
  per-job fallback only for entries missing from the response). `run()`'s loop was
  restructured into distinct tailor/verify/update phases to support it.
- ~~**#10 — Double-edit-in-one-paragraph clobber** in `render_docx.py`.~~ ✅ Fixed (PR
  #16, `fix/pr11-issue10-same-paragraph-double-edit-clobber`). `apply_docx_edits()` now
  resolves every paragraph's edits against a fixed original-text snapshot instead of
  sequentially-mutated text, and rejects genuinely overlapping spans rather than
  guessing. See `test_apply_docx_edits_sequential_same_paragraph_edits_dont_clobber`.
- ~~**#11 — `draft_cold_emails_batch`**'s `except` falls back to N individual calls on a
  hard failure.~~ ✅ Fixed (PR #17, `fix/pr11-issue11-cold-email-batch-failure-fallback`).
  The batch AI call is now wrapped in its own `try`/`except`, separate from response
  parsing. A hard exception from the call itself (post-retry `AIChatError`, etc.) no
  longer triggers per-job fallback calls; it returns a `_draft_failed()` placeholder per
  job (mirroring `stage1_scrape.py`'s `_unscored()` contract) and `run()` skips writing a
  draft for that job, leaving it for the next run. The legitimate "response received but
  unparseable/entry missing" fallback is unchanged. See
  `tests/test_stage3_outreach_contract.py::test_draft_cold_emails_batch_does_not_amplify_on_hard_batch_failure`.

Full suite (243 tests) green on `feature/god-speed` with all six merged.

---

## 5. Minor

- Every dependency is unpinned (`>=`, no `==`) except `notion-client`, which correctly
  carries an upper bound — worth extending that discipline for a reproducible nightly
  run.
- `playwright` sits in `requirements.txt` unconditionally despite being documented as
  optional, so CI installs it even where it's never used.
- `render_docx.py`'s module docstring still describes it as the `docxtpl` renderer,
  which is no longer its primary role.
- `extract_docx_text` / `apply_docx_edits` ignore `doc.tables` — latent only (the resume
  has no tables today), but would fail silently if the resume is ever restructured to
  use one.

---

## 6. Verified clean

- No hardcoded secrets across the whole diff.
- `.claude/` (18 files), `docs/` (15 files), and the test fixtures are documentation/data
  only — skimmed, no logic risk.
- `tests.yml` needs no secrets and passes.
- `stage6_negotiate.py` and `spike_phase0_leads.py` are self-contained and guarded.

---

## 7. Revised verdict (2026-07-21)

The earlier "approve with follow-ups" pass covered 10 of 99 files and was too generous.
The four contained bugs it should have surfaced (`render_docx` run-flattening plus the
three stage 2/3 cross-assignment paths) were all found in the full-diff pass and have
since been **fixed and merged** via PR #12 — confirmed directly against
`gh api .../contents/<file>?ref=feature/god-speed` in this pass, not inferred.

**The merge itself remains safe** — clean fast-forward, CI green, 162 tests. What's left
open from this review, re-verified 2026-07-21:

| # | Item | File | Status |
|---|------|------|--------|
| 1 | Run-flattening formatting bug | `scripts/render_docx.py:132` | ✅ Fixed (PR #12) |
| 2 | Same-company resume collision | `scripts/stage2_tailor.py:280` | ✅ Fixed (PR #12) |
| 3 | Positional outreach misalignment | `scripts/stage3_outreach.py:96` | ✅ Fixed (PR #12) |
| 4 | Same-company email collision | `scripts/stage3_outreach.py:183` | ✅ Fixed (PR #12) |
| 5 | Nightly `stage3`/`stage5` dispatch modes crash on `input()` | `.github/workflows/nightly-pipeline.yml`, `run.py:158`, `stage5_interview_prep.py:144` | ⏳ Open |
| 6 | Zero-edit tailoring still marked `Resume Tailored` | `stage2_tailor.py` | ✅ Fixed (PR #13) |
| 7 | `python-docx` undeclared in `requirements.txt` | `requirements.txt` | ✅ Fixed (PR #15) |
| 8 | `fetch_jd()` doesn't strip `<script>`/`<style>` before the AI call | `stage2_tailor.py` | ✅ Fixed (PR #14) |
| 9 | `verify_tailored_score()` is N calls, not batched | `stage2_tailor.py` | ✅ Fixed (PR #18) |
| 10 | Double-edit-in-one-paragraph clobber | `render_docx.py` | ✅ Fixed (PR #16) |
| 11 | `draft_cold_emails_batch` amplifies failure on hard batch exception | `stage3_outreach.py` | ✅ Fixed (PR #17) |
| 12 | Dependencies unpinned except `notion-client` | `requirements.txt` | ⏳ Open (minor) |
| 13 | `playwright` installed unconditionally despite being optional | `requirements.txt` | ⏳ Open (minor) |
| 14 | Module docstring still described `docxtpl` renderer | `scripts/render_docx.py` | ✅ Fixed (PR #15) |
| 15 | `doc.tables` ignored in docx text extraction/edits (latent) | `scripts/render_docx.py` | ⏳ Open (minor) |

**Remaining:** only #5 (nightly workflow's `input()` crash on unattended `stage3`/`stage5`
dispatch) and the minor cleanup items #12/#13/#15 are still open.

---

*Generated as a review aid for PR #11. Section 1–2 originally flagged these as blocking;
both were resolved by PR #12 before this update and are kept here (struck through, not
deleted) as a record of what was found and fixed. Update the table in §7 as further
items are resolved.*
