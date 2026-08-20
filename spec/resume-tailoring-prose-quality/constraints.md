# Constraints

## The anti-fabrication rules in `SYSTEM_PROMPT` are non-negotiable

`scripts/stage2_tailor.py:32-38` — "Never invent experience, employers, degrees, dates, or
metrics", "Never change the candidate's name, contact info, company names, or employment dates."
Any prompt change for "more liberal sentence expansion" must keep these verbatim or
strengthen them, never loosen them. A resume with a fabricated-sounding claim is a materially worse
outcome than a keyword-awkward one.

## `"old"` must still resolve to real, findable text

`apply_docx_edits()` matches `"old"` as an exact substring of some paragraph's current text
(`render_docx.py:237-`). Any prompt change that lets `"new"` be a fuller sentence rewrite must keep
`"old"` as a verbatim, findable span — the mechanism doesn't change, only how much of the sentence
the edit is allowed to touch. If Workstream A's investigation concludes edits need to span multiple
paragraphs or restructure bullet boundaries, that's a `render_docx.py` mechanism change, not just a
prompt change — flag it explicitly in plan.md rather than silently expanding scope.

## `verify_tailored_score()` stays the guardrail against prose-for-score tradeoffs

Post-tailor re-scoring (`stage2_tailor.py:395`, `MIN_TAILORED_ATS_SCORE` warning at `:643`) already
exists specifically to catch a regression. Any prompt change here must be validated against
`scripts/run_evals.py`'s `--tailor` before-vs-after ATS delta (per CLAUDE.md's "Testing a Change"
§2) — a prompt that reads better to a human but tanks the ATS delta hasn't actually improved
anything the pipeline optimizes for.

## No hand-labeled "prose quality" eval exists yet

Unlike ATS score (`tests/eval_data/jobs.json`), there's no existing rubric for "does this bullet
read naturally." A prompt-only change is hard to validate objectively — the acceptance bar here is
necessarily partly qualitative (a human skim of before/after samples), not purely a metric, until
such a rubric exists.
