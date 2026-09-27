# Communications subsystem (Stages 7-8: LinkedIn leads + verified cold email)

**Status:** superseded — 2026-09-27, see [triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61)
and closed [#53](https://github.com/Iamkach/careerpilot-ai/issues/53). The XL design below is
**dropped** (too heavy for a P3 want while the core pipeline has known flaws to fix first).
Merged into a lightweight, agentic browser-workflow fog item alongside `wellfound-job-source` and
`inbound-email-status-sync` on #61's "Not yet specified" — reads email/job-board state back into
the tracker without the Notion DB / new-stage build below. Not yet scoped into a real ticket.
**Priority:** — (was P3)
**Size:** — (original XL estimate no longer applies; new approach unscoped)
**Depends-on:** [] — depends on Step 6 (benefits from an earlier LinkedIn actor swap that hands
this story free recruiter contact data) and Step 5 (`classify_company_type()` decision), neither
yet migrated into `spec/`.

Original framing (superseded, kept for context):

Two prongs, one subsystem: (1) find the people attached to live job reqs (poster, recruiter,
hiring manager) via LinkedIn, keep them as durable Leads, draft targeted outreach behind a manual
approval gate; (2) for top-ATS jobs, identify who's worth contacting and resolve a **verified**
professional email via Hunter.io.

Originally drafted in `refinement-plans/communications/communications-subsystem.md` (finalized and
folded into this doc — no separate refinement doc remains). Migrated from
`docs/backlog/step-7-communications-subsystem.md` into this `spec/` structure.
