# Verification (when implemented)

## Workstream A

1. `pytest -v` stays green, including a new/updated test proving `apply_docx_edits()` correctly
   applies a full-sentence-length `"new"` replacement (multi-run paragraph edge case).
2. `python scripts/run_evals.py --tailor` run before and after the prompt change, comparing the
   stage 2 before→after ATS delta — must not regress versus the pre-change baseline, per
   CLAUDE.md's "Testing a Change" §2.
3. Manual: run `python run.py --stage 2 --min-score 0` (or the `run_evals.py --tailor` sample)
   against 5-10 real `Reviewed` jobs, read the before/after tailored bullets side by side, confirm
   they read as fluent sentences rather than keyword-spliced ones, and confirm no fabricated
   detail crept in (cross-check each changed bullet against the base resume + JD by hand).
4. Confirm the `.docx` output still opens correctly and preserves formatting (bold/bullets/spacing)
   in Word/LibreOffice — the same manual check any `render_docx.py` change already warrants.

## Workstream B

1. After the user's content update lands in `config/resume.docx`, run `extract_docx_text()`
   against it and manually confirm the extracted text matches what's actually in the document (no
   corrupted paragraphs/tables).
2. Run Stage 2 against one real `Reviewed` job and confirm edits still apply and the tailored
   `.docx` + `.txt` mirror both look correct.
3. Confirm `config/resume.txt` (the plain-text fallback) reflects the same content as the updated
   `.docx`.
