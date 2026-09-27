# Resume tailoring prose quality + template update

**Status:** finalized — elevated to top priority 2026-09-27, see
[triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61) (tracked as
[#51](https://github.com/Iamkach/careerpilot-ai/issues/51) and
[#52](https://github.com/Iamkach/careerpilot-ai/issues/52)): user overrode an initial "defer"
recommendation — this is affecting actual application quality, not cosmetic. Ranked #1 of 5.
**Priority:** P1 (#1 of 5 in #61's top-5 ranking)
**Size:** M (prompt/formatting changes are contained to Stage 2 + `render_docx.py`; a template
content rewrite is separately-scoped manual work, see non-goals.md).
**Depends-on:** []

Written down at the user's request: Stage 2's current tailoring edits ({old, new} verbatim-text
substitutions) read as narrow keyword injection rather than well-formed prose, and the underlying
`config/resume.docx` template itself is due for a content update. Two related but separable asks —
prompt/edit-mechanics quality, and the base template's own content — captured together here since
the user raised them together, split into two workstreams below.
