# End goal

**Workstream A:** A tailored resume's edited bullets/summary read as fluently and naturally written
sentences — not a base sentence with a keyword wedged in — while still passing the exact same
anti-fabrication bar as today (no invented tools/companies/dates/metrics, no changed employment
facts). The AI is given room to rewrite a full sentence/bullet around the keywords it's adding,
not just splice a phrase into the existing wording, and `apply_docx_edits()`'s verbatim-`old`-match
mechanism is confirmed to keep working with larger, more thoroughly rewritten `new` spans (or is
adjusted if a full-paragraph-swap mode turns out to be needed instead of the current substring-span
mode). `verify_tailored_score()`'s post-tailor ATS re-scoring stays the acceptance gate it already
is — the goal is better prose at the same-or-better score, not prose quality traded against score.

**Workstream B:** `config/resume.docx` reflects the user's current, intended content — done once the
user provides what should change; this doc doesn't presume the content, only that the process is
"user supplies new text/structure → apply directly to the docx" rather than an AI-authored resume
rewrite (a resume's factual content is the user's call, not something to generate).
