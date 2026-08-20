# Problem

## Workstream A — tailoring prompt produces narrow, minimal edits by design

Stage 2's tailoring prompts (`_tailor_resume_single()` / `_tailor_resumes_chunk()` in
`scripts/stage2_tailor.py`) explicitly instruct the model toward minimal, surgical edits:

- "Rewrite minimally — change only what's needed to include the keyword naturally"
  (`scripts/stage2_tailor.py:170`)
- "only add missing terminology where it genuinely fits" (`:175`, `:264`)
- "Prefer depth over breadth: 5 strong edits beats 15 shallow ones" (`:177`, `:265`)

This is a deliberate anti-fabrication guardrail (`SYSTEM_PROMPT` at `:32-38`: "Never invent
experience... Never change... only add missing terminology"), not an accident — but its side effect
is that edited bullets often read as a keyword awkwardly grafted onto an otherwise-unchanged
sentence, rather than a fluently rewritten one. The user's ask is for materially better sentence
construction and more liberal (but still fact-bound) expansion of the sentence itself, not just
keyword insertion.

## Mechanical constraint compounding this

`apply_docx_edits()` (`scripts/render_docx.py:237`) does exact verbatim substring matching against
the *original* paragraph text (`"old"` must match character-for-character) and patches only the
matched span's run(s) in place. This means:

- The AI can't restructure a sentence across paragraph boundaries or reflow a bullet's line breaks
  — each edit is confined to one paragraph's existing text.
  is bound by
  what already exists to substitute against, not what would read best from scratch.
- A larger "new" replacement is mechanically fine (the run's text is simply replaced), but the AI
  has been prompted toward small `old` spans, keeping edits keyword-sized rather than
  sentence-sized.

## Workstream B — base template due for a content refresh

`config/resume.docx` (`RESUME_TEMPLATE_PATH`) is the source every tailored resume is copied from
(`save_resume()` in `stage2_tailor.py:340`) and where `apply_docx_edits()` matches "old" text
against. Its content is the user's own and not something this repo can infer from code — the user
wants to update it (presumably new experience, adjusted framing, or refreshed bullets) but hasn't
yet said what changes. This half of the problem is scoped as a content-editing task once the user
supplies the new content, not a code change.
