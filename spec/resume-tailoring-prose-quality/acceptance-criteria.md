# Acceptance criteria

## Workstream A — prompt/edit-mechanics quality

- [ ] Phase 0 spike (sample before/after edits against real JDs, human skim-review — see plan.md)
      completed before the prompt change ships.
- [ ] Updated `SYSTEM_PROMPT` / edit-priority instructions in both `_tailor_resume_single()` and
      `_tailor_resumes_chunk()` (kept in sync — they currently duplicate the same rules) explicitly
      permit rewriting a full bullet/sentence around a keyword, not just splicing a phrase in,
      while keeping every anti-fabrication constraint verbatim or stronger.
- [ ] `apply_docx_edits()` is confirmed (via a test) to still correctly apply a larger, fuller-
      sentence `"new"` replacement against its matched `"old"` span, including a multi-run
      paragraph.
- [ ] `python scripts/run_evals.py --tailor` shows the before→after ATS delta does not regress
      versus the pre-change baseline (per CLAUDE.md's "Testing a Change" §2).
- [ ] A hand-reviewed sample of 5-10 before/after tailored bullets shows materially improved
      sentence construction (human judgment call, documented in the eval run's notes since no
      automated prose-quality metric exists yet).

## Workstream B — template content

- [ ] User has supplied the specific content changes wanted for `config/resume.docx`.
- [ ] Updated `config/resume.docx` is a valid `.docx` that `extract_docx_text()` /
      `apply_docx_edits()` can still parse and match against — verified by running Stage 2 against
      a sample job after the update.
- [ ] `config/resume.txt` (the fallback used when the `.docx` is absent) stays in sync if the
      textual content changed, per `load_base_resume_text()`'s fallback path
      (`scripts/stage2_tailor.py:43-51`).
