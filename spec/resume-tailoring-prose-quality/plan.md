# Plan

## Open questions / Phase 0 spike (do before any code)

1. **What does "better sentence formatting" mean concretely?** Get 2-3 concrete before/after
   examples from the user (or generate candidate rewrites against a real JD and have the user
   react to them) before touching the prompt — "more liberal expansion" is directional, not yet a
   spec-able rule the AI can follow precisely. Turn the reaction into a short positive/negative
   example pair to embed in the prompt itself (few-shot beats abstract instruction for prose-style
   changes).
2. **Check whether `apply_docx_edits()`'s substring-span mechanism is actually the bottleneck**, or
   whether the prompt's own "rewrite minimally" instructions are — test by manually relaxing just
   the prompt wording first (`old` spans can already be as large as a full sentence/bullet; nothing
   in `render_docx.py` requires a small span) before concluding a `render_docx.py` change is needed
   at all. This determines whether Workstream A is prompt-only (likely) or also touches
   `render_docx.py` (only if spans need to cross paragraph boundaries).
3. **Workstream B kickoff:** ask the user what specifically should change in `config/resume.docx`
   (new role/experience, reframed summary, updated skills, different bullet emphasis) — this can't
   be planned further without that input.

## Files (when implemented, Workstream A)

- **Modify:** `scripts/stage2_tailor.py` — `SYSTEM_PROMPT`, the edit-priority instructions in both
  `_tailor_resume_single()` (`:159-185`) and `_tailor_resumes_chunk()` (`:249-280`, which currently
  duplicate the same rules and must stay in sync), adding a few-shot example pair from Phase 0
  question 1 and explicit permission to rewrite a full bullet/sentence.
- **Possibly modify:** `scripts/render_docx.py`'s `apply_docx_edits()` / `_apply_para_edits()` —
  only if Phase 0 question 2 finds the substring-span mechanism itself (not the prompt) is the
  binding constraint (e.g. needing to merge/split paragraphs, not just replace a longer span within
  one).
- **New/modify:** a fixture in `tests/` proving `apply_docx_edits()` correctly applies a full-
  sentence-length replacement spanning multiple runs within one paragraph (formatting like bold/
  italic mid-sentence is the likely edge case worth a dedicated test).
- **Run, not modify:** `scripts/run_evals.py --tailor` against `tests/eval_data/jobs.json` for the
  before/after ATS delta check required by acceptance-criteria.md.

## Files (when implemented, Workstream B)

- **Modify:** `config/resume.docx` (binary — edited via Word/LibreOffice by the user, or via a
  one-off `apply_docx_edits()`-style script if the changes are mechanical find/replace) and
  `config/resume.txt` (kept in sync, per constraints.md).

## Risks

- **Prose-quality drift is hard to catch automatically.** Unlike ATS score, there's no regression
  test for "does this still read well" — acceptance leans on a human skim (acceptance-criteria.md),
  which won't scale if this prompt gets touched again later without the same discipline. Worth
  flagging as a candidate for a future `tests/eval_data/`-style hand-labeled prose-quality set if
  this keeps needing re-tuning.
- **Looser edit instructions risk creeping fabrication.** The exact failure mode `SYSTEM_PROMPT`
  guards against — this is the reason Phase 0's before/after review and the ATS-delta check both
  gate the change, not just a prompt edit merged on vibes.
- **Workstream B has no code risk but a real data-loss risk** if the `.docx` is hand-edited outside
  `apply_docx_edits()` and its structure changes enough that future automated edits stop matching
  paragraphs correctly — worth a quick manual Stage 2 dry run against the updated template before
  trusting it in the live pipeline (already captured in acceptance-criteria.md).
