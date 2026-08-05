# Problem

Nothing in this repo reads Gmail today. `GMAIL_CREDENTIALS_PATH` (`config/settings.py:466`) backs
exactly one call site — `send_via_gmail()` in `scripts/stage4_digest.py:191` — which only *sends*
the morning digest via `service.users().messages().send(...)`. The stored OAuth credential is
therefore send-scoped (`gmail.send` or `gmail.compose`, whatever the original consent flow granted)
and cannot list or read messages; a status-sync feature needs a broader scope
(`gmail.readonly` or `gmail.modify` if it also applies labels — see constraints.md), which means
**a fresh OAuth consent flow**, not a reuse of the existing credential file.

The Jobs Tracker's pipeline statuses (`Applied → Outreach Sent → Interview Scheduled → Offer
Received`, plus the off-pipeline `Rejected`) are all hand-set today — see CLAUDE.md's "Off-pipeline
states... exist as select options and are set **by hand** — no stage writes them" (with the one
carved-out exception being Stage 2's sponsorship gate). This plan proposes the second stage to ever
write one of these statuses automatically, so it inherits that section's caution by design, not by
accident.

## Goal

For each Notion job currently sitting in an "in-flight" status (`Applied`, `Outreach Sent`,
`Interview Scheduled` — i.e. already submitted, waiting on the company), watch the inbox for a
reply from that company and, when one arrives:

1. Match the email to the right tracker row.
2. Classify what kind of signal it is (rejection / interview invite / online assessment /
   offer / recruiter follow-up / unrelated).
3. Either update Notion `Status` (only for a small, high-confidence, unambiguous subset) or leave
   `Status` untouched and just log the signal for the human to act on — **the classification and
   the status write are two different confidence bars, and most emails should only clear the first
   one.**

## Governing rule (mirrors the auto-apply subsystem's, same reasoning)

**The Gmail API supplies facts; AI only classifies and ranks.** The AI never invents which job a
message belongs to — a code-level filter narrows the candidate set *before* the AI ever sees the
message (see plan.md's "Matching"), and a code-level validator rejects any AI response naming a
`job_id` outside that pre-filtered set. This is the same shape as the communications-subsystem
spec's AI ranking guardrail and the auto-apply subsystem's rule that work-authorization answers
come from the profile, never a guess — applied here to "which job does this email belong to" and
"did this company actually reject me."

**A wrong write here is asymmetric and worse than a wrong write anywhere else in the pipeline.**
Auto-marking a live interview thread `Rejected` hides a job the user should still be pursuing, and
nothing else in the system would ever surface that mistake — the row just quietly stops showing up
in digests. This is the same asymmetry CLAUDE.md calls out for Stage 7 never writing `Applied`
("you stop re-applying to jobs you never actually applied to"). The mitigation is the same shape:
default to the conservative side, and make the confident side narrow and auditable.
