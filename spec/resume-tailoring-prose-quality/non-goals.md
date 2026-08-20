# Non-goals

- **AI-authored resume content for the base template.** Workstream B is the user supplying their
  own updated experience/bullets; this feature doesn't propose generating new resume content from
  scratch (that would risk exactly the fabrication problem the tailoring prompt already guards
  against, just moved earlier in the pipeline).
- **Loosening the anti-fabrication guardrails.** "More liberal sentence expansion" means better
  sentence construction around real facts already on the resume or genuinely supported by the JD's
  terminology — not permission to invent metrics, scope, or responsibilities that make a bullet
  read more impressively than the underlying fact supports.
- **Changing `MIN_TAILORED_ATS_SCORE`'s enforcement posture.** It stays a logged warning, not a
  blocking gate, exactly as today — this feature is about the prose quality of a *passing* edit,
  not about tightening or loosening the score check itself.
- **A full docx template redesign (fonts, layout, section order).** Nothing in the user's ask
  implies a visual redesign — `apply_docx_edits()`'s in-place run-patching approach already
  preserves formatting by design, and this feature doesn't propose replacing that mechanism unless
  Workstream A's investigation finds it's actually blocking (see plan.md).
