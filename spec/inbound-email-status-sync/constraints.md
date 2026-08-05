# Constraints

## Status write policy

| Signal | Confidence | Candidate count | Action |
|---|---|---|---|
| `rejection` | ≥ threshold (e.g. 85) | exactly 1 | Write `Status = Rejected` |
| `interview_invite` | ≥ threshold | exactly 1 | Write `Status = Interview Scheduled` |
| `offer` | ≥ threshold | exactly 1 | Write `Status = Offer Received` |
| `assessment` | any | any | **No status write** — no pipeline status fits "OA received" without inventing one; log only |
| `recruiter_followup` / `unrelated` | any | any | No status write |
| anything | below threshold | any | No status write |
| anything | any | > 1 (ambiguous, AI picked one) | No status write — ambiguity itself is a reason to hold back, even if the AI is confident about its pick |

**Never downgrades.** A job already at `Interview Scheduled` is never moved back to `Applied` by
this stage even on a confusing signal — the write path only ever moves a job to `Rejected` /
`Interview Scheduled` / `Offer Received`, all of which are terminal-ish or forward progress; there
is no code path that regresses a status.

**Every match — written or not — gets an audit trail entry**, the same pattern `db_add_job`
already uses to cache the JD in the page body: append a block to the job's Notion page body
(`📧 2026-07-28 — rejection (94% conf.) from careers@acme.com: "We've decided to move forward with
other candidates..."`) so the human sees *why* even when no status changed, and so a later review
of a `review_required`-style ambiguous case has the actual email text next to it instead of a bare
notification. This is the same "log it, human decides" posture CLAUDE.md documents for Stage 2's
`verify_tailored_score()` warning.

## Dedupe / watermarking (ephemeral-runner-safe)

Same constraint the communications-subsystem spec already worked through for GitHub Actions: no
local SQLite, no reliance on runner disk surviving between runs. Reuse that resolution — **Gmail
labels, not a local watermark file.** Apply a `CareerPilot/Synced` label (via `messages().modify`,
hence needing `gmail.modify` scope rather than just `gmail.readonly`) to every message this stage
has already processed, and query `-label:CareerPilot/Synced` each run. This is stateless from the
pipeline's side — the state lives in Gmail itself, which survives independent of the runner — and
it doubles as a visible audit trail in the inbox.

## Notion schema additions (minimal, by design)

No new `Status` options needed — `Rejected`, `Interview Scheduled`, `Offer Received` already
exist. Two small additions, both optionally-present the same way Step 6's multi-source fields are
(`_notion_write_job()` pattern — absence doesn't break the write, the column just stays empty
until added):

- `Last Email Signal` (select: `rejection`, `interview_invite`, `assessment`, `offer`,
  `recruiter_followup`, `unrelated`) — the most recent classification, for a digest section to
  filter on later.
- `Last Email Synced` (date) — when this row was last touched by the sync, mostly for debugging.

The actual email text/reasoning lives in the page body audit trail above, not as a Notion
property — same "don't property-sprawl, cache detail in the body" precedent as the cached JD.
