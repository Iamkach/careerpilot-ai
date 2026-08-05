# Inbound email → application status sync

**Status:** idea — not queued.
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
