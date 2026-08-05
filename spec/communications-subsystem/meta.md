# Communications subsystem (Stages 7-8: LinkedIn leads + verified cold email)

**Status:** idea — blocked on its own Phase-0 spike; nothing downstream is written until that
returns.
**Priority:** P3 — most complex story in the roadmap; last for a reason.
**Size:** XL — two new stages, a new Notion database (~22 props), a new module, a digest refactor,
two new vendors, a new execution model (GitHub Actions).
**Depends-on:** [] — depends on Step 6 (benefits from an earlier LinkedIn actor swap that hands
this story free recruiter contact data) and Step 5 (`classify_company_type()` decision), neither
yet migrated into `spec/`.

Two prongs, one subsystem: (1) find the people attached to live job reqs (poster, recruiter,
hiring manager) via LinkedIn, keep them as durable Leads, draft targeted outreach behind a manual
approval gate; (2) for top-ATS jobs, identify who's worth contacting and resolve a **verified**
professional email via Hunter.io.

Originally drafted in `refinement-plans/communications/communications-subsystem.md` (finalized and
folded into this doc — no separate refinement doc remains). Migrated from
`docs/backlog/step-7-communications-subsystem.md` into this `spec/` structure.
