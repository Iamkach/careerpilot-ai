# Non-goals

- **Auto-drafting a reply to any inbound email.** This stage only reads and classifies; sending
  stays entirely manual (Stage 4's `--send` is the only existing send path, and it's a fixed
  digest, not a reply).
- **Any status other than `Rejected` / `Interview Scheduled` / `Offer Received` being auto-written.**
  `Assessment Received` as a new status is deliberately not proposed here — log-only is enough
  until real usage shows an OA-tracking gap that logging doesn't cover.
- **Full thread/conversation tracking** (e.g. tracking an interview-scheduling back-and-forth
  across multiple messages). One classification per message is enough for the stated goal (status
  sync), not a general inbox-CRM feature.
- **Ever downgrading a status.** A job already at `Interview Scheduled` is never moved back to
  `Applied` by this stage even on a confusing signal — the write path only ever moves a job
  forward, never backward.
