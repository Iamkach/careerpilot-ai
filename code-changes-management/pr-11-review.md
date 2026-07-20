# PR #11 — Full Review (102 files, +11,775 / −1,906)

> **Catch up main: pipeline rewrite, multi-source sourcing, test suite**
> Base: `main` ← Head: `feature/god-speed`
> Author: Krishna Achyuth (`Iamkach`)
> PR: https://github.com/Iamkach/careerpilot-ai/pull/11
> State: **OPEN** · Latest reviewed commit: `2f00d97`

This is the full-diff follow-up review (previous pass covered 10 of 99 files and is
superseded by this one). CI status: `pytest` green in ~27s on the latest push — the
earlier `startup_failure` seen on this workflow was a transient GitHub Actions issue,
not a config problem, and is **not** tracked as an open item.

---

## 1. Blocking

### 🔴 Silent formatting corruption in delivered resumes — `scripts/render_docx.py:132`

`_replace_para_text()` collapses every run in a paragraph into `runs[0]`, so the whole
line inherits the first run's formatting. Reproduced against the actual
`Achyuth_Resume.docx`:

```
BEFORE:  'Languages & Frameworks: '                    bold=True
         'Java, Python, JavaScript, TypeScript, ...'   bold=None
AFTER:   'Languages & Frameworks: Java, Python, ...'   bold=True   ← entire line
```

Not theoretical — the resume has 12 mixed-formatting paragraphs, and they're exactly
what stage 2's prompt targets (priority #3: "TECHNICAL SKILLS: append missing keywords
to existing lines"). All four skills lines are bold-label + normal-list; the three
experience headers (bold title | normal company | italic dates) are equally exposed.

So the most common tailoring edit silently bolds an entire skills line in the `.docx`
sent to employers. Nothing catches it: the `.txt` mirror is text-only, and
`verify_tailored_score()` re-scores text, so the ATS score stays fine while the document
itself degrades. The docstring's tradeoff ("acceptable for resume bullets where a whole
bullet shares the same style") holds for the 30 single-run paragraphs but not the 12
that matter most.

**Fix:** locate the run(s) containing `old` and splice within them, preserving each
run's own formatting, instead of flattening to `runs[0]`.

---

## 2. Cross-assignment: wrong content attached to the wrong job

Three independent paths, all silent, all in the "output looks plausible" direction —
none covered by a test.

1. **`scripts/stage2_tailor.py:280`** — same-company collision. `by_company` is keyed on
   lowercased company name. Two `Reviewed` roles at one company (a normal outcome of a
   real job search) → the second overwrites the first, and if `by_index` misses, a job
   gets *another role's* resume edits — saved and marked `Resume Tailored`.
2. **`scripts/stage3_outreach.py:96`** — positional alignment.
   `entry = data[i] if i < len(data) else {}` ignores the `company` field the model
   returns. One omitted or reordered entry shifts every subsequent company mapping,
   while the saved file's header still shows the *correct* company (it comes from the
   loop var, not the model output) — masking the mismatch. Weakest of the three, since
   stage 1 keys by URL and stage 2 at least attempts `job_index`.
3. **`scripts/stage3_outreach.py:183`** — same collision pattern as #1:
   `email_by_company` re-keys by company, so two roles at one employer both get the
   second role's email.

**Fix:** key all three by `page_id` (the Notion page id already threaded through the
job dict) instead of company name / list position.

---

## 3. Two nightly workflow modes are broken by construction

`nightly-pipeline.yml` offers `stage3` and `stage5` as `workflow_dispatch` modes, but:

- `run.py:158` `stage3()` doesn't pass `no_confirm`, so `stage3_outreach.py:175,199`
  calls `input()`. Only `--evaluate` passes it through today.
- `stage5_interview_prep.py:144,149` calls `input()` unconditionally.

In Actions, stdin is `/dev/null` → `EOFError` → job fails every time it's invoked.

**Fix:** either thread `no_confirm` through `--stage 3` (and add a non-interactive path
for stage 5), or drop those two modes from the workflow's dispatch options until they're
non-interactive.

---

## 4. Worth fixing

- **`stage2_tailor.py:422`** — status advances to `Resume Tailored` even when `edits` is
  empty. A zero-edit run produces a renamed copy of the base resume presented as
  tailored — the same "don't claim success you didn't achieve" principle stage 7's
  *Never `Applied`* rule already enforces, applied inconsistently here.
- **`python-docx` is undeclared.** `render_docx.py` imports it directly, but
  `requirements.txt` only lists `docxtpl` (CLAUDE.md documents that path as dead/legacy).
  Add `python-docx`; remove `docxtpl` once confirmed unused elsewhere.
- **`stage2_tailor.py:94`** `fetch_jd()` strips tags without removing
  `<script>`/`<style>` first, so JS/CSS text can land in the JD sent to the model.
  `sources._strip_html()` already handles this correctly — reuse it instead of a second,
  weaker implementation.
- **`verify_tailored_score()`** issues one AI call per job in phase 3, undercutting the
  "one batch AI call" design from phase 2. N jobs → N extra quality-tier calls.
- **`draft_cold_emails_batch`**'s `except` falls back to N individual calls. On a real
  outage this turns 1 failed call into N more, each with its own 3-attempt retry —
  amplifies the failure instead of degrading gracefully.

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

## 7. Revised verdict

The earlier "approve with follow-ups" pass covered 10 of 99 files and was too generous.
The `render_docx` flattening bug alone would degrade every tailored resume sent out, and
it's invisible from the Notion tracker (ATS score stays healthy while the document
itself corrupts).

**The merge itself remains safe** — clean fast-forward, CI green, 215 tests. But the four
contained bugs below should land before stage 2 is run again for real applications:

| # | Item | File |
|---|------|------|
| 1 | Run-flattening formatting bug | `scripts/render_docx.py:132` |
| 2 | Same-company resume collision | `scripts/stage2_tailor.py:280` |
| 3 | Positional outreach misalignment | `scripts/stage3_outreach.py:96` |
| 4 | Same-company email collision | `scripts/stage3_outreach.py:183` |

**Plan:** separate branch off `feature/god-speed` (or `main`, once #11 merges) rather
than more commits onto an already-large PR. Tests first, per the "every change ships
with a test" rule — write the reproducing test before the fix for each of the four.

---

*Generated as a review aid for PR #11. Supersedes the prior partial pass. Update the
checklist above as items are resolved.*
