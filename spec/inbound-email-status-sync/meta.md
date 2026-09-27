# Inbound email → application status sync

**Status:** superseded — 2026-09-27, see [triage map #61](https://github.com/Iamkach/careerpilot-ai/issues/61)
and closed [#54](https://github.com/Iamkach/careerpilot-ai/issues/54). Merged into a lightweight,
agentic browser-workflow fog item alongside `communications-subsystem` and `wellfound-job-source`
on #61's "Not yet specified" — the design below (a dedicated read-inbox pipeline stage) is not
being built as scoped; not yet reworked into a real ticket.
**Depends-on:** []

Written down at the user's request after noticing the pipeline is one-directional: every stage
writes *toward* Notion, but nothing ever reads back what happens after a human clicks Submit. Once
a job reaches `Applied` (or a human hand-sets `Interview Scheduled` / `Rejected` / `Offer
Received`), the tracker goes silent — the user still combs their own inbox and updates Notion by
hand for every reply an ATS or recruiter sends. This is the design for closing that loop: read the
inbox, match a message to a tracker row, classify what it says, and update Notion — without ever
mis-closing a job that's still alive.

Migrated from `docs/refinement-plans/tracking/inbound-email-status-sync.md` into this `spec/`
structure.
