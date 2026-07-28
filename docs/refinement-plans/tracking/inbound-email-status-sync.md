# Inbound email → application status sync

*See [`../README.md`](../README.md) for how this plan relates to the others.*

**Status (2026-07-28): idea-level, not queued.** Written down at the user's request after noticing
the pipeline is one-directional: every stage writes *toward* Notion, but nothing ever reads back
what happens after a human clicks Submit. Once a job reaches `Applied` (or a human hand-sets
`Interview Scheduled` / `Rejected` / `Offer Received`), the tracker goes silent — the user still
combs their own inbox and updates Notion by hand for every reply an ATS or recruiter sends. This
doc is the design for closing that loop: read the inbox, match a message to a tracker row, classify
what it says, and update Notion — without ever mis-closing a job that's still alive.

## Context

Nothing in this repo reads Gmail today. `GMAIL_CREDENTIALS_PATH` (`config/settings.py:466`) backs
exactly one call site — `send_via_gmail()` in `scripts/stage4_digest.py:191` — which only *sends*
the morning digest via `service.users().messages().send(...)`. The stored OAuth credential is
therefore send-scoped (`gmail.send` or `gmail.compose`, whatever the original consent flow granted)
and cannot list or read messages; a status-sync feature needs a broader scope
(`gmail.readonly` or `gmail.modify` if it also applies labels — see below), which means **a fresh
OAuth consent flow**, not a reuse of the existing credential file.

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

## Governing rule (mirrors Step 7's, same reasoning)

**The Gmail API supplies facts; AI only classifies and ranks.** The AI never invents which job a
message belongs to — a code-level filter narrows the candidate set *before* the AI ever sees the
message (see "Matching," below), and a code-level validator rejects any AI response naming a
`job_id` outside that pre-filtered set. This is the same shape as Step 7's ranking guardrail
(`docs/backlog/step-7-communications-subsystem.md`, Phase 4) and Stage 7 auto-apply's rule that
work-authorization answers come from the profile, never a guess — applied here to "which job does
this email belong to" and "did this company actually reject me."

**A wrong write here is asymmetric and worse than a wrong write anywhere else in the pipeline.**
Auto-marking a live interview thread `Rejected` hides a job the user should still be pursuing, and
nothing else in the system would ever surface that mistake — the row just quietly stops showing up
in digests. This is the same asymmetry CLAUDE.md calls out for Stage 7 never writing `Applied`
("you stop re-applying to jobs you never actually applied to"). The mitigation is the same shape:
default to the conservative side, and make the confident side narrow and auditable.

## Matching: email → job row

Restrict the candidate set with code before any AI call:

1. Pull the in-flight snapshot: `db_get_jobs(status)` for each of `Applied`, `Outreach Sent`,
   `Interview Scheduled` (reuse the existing helper — no new Notion read primitive needed).
2. For each unprocessed inbound message (see dedupe, below), narrow to jobs whose `Company`
   fuzzy-matches the sender's domain or display name. Reuse `job_fingerprint()`'s normalization
   idea (`scripts/sources.py`) rather than inventing new string-matching — strip legal suffixes,
   lowercase, compare.
3. If that narrows to **exactly one** candidate job → high-confidence match, proceed to
   classification with that job pinned (no AI guessing needed for *which* job).
4. If it narrows to **more than one** (e.g. two open reqs at the same company) → pass all
   candidates to the AI classifier and let it pick using subject-line/body context (job title
   keywords), but the code-level validator still rejects any answer whose `job_id` isn't in that
   candidate set — the AI narrows among knowns, it doesn't invent a new match.
5. If it narrows to **zero** → no update, no AI call. Not every inbound email is job-related; most
   won't match anything, and that's the expected common case, not an error.

This mirrors Step 7's own guardrail almost exactly (`docs/backlog/step-7-communications-subsystem.md`
Phase 4: "validate every returned `idx` against the input set and drop anything referencing a
name/email not present in it").

## Classification

One AI call per (message, candidate-job-set) pair, cheap tier (`ai_chat(..., quality=False)` —
this is high-volume, low-stakes text classification, the same tier as Stage 1 scoring). Output
shape:

```
{"job_id": "<one of the candidate ids>", "signal": "rejection|interview_invite|assessment|offer|recruiter_followup|unrelated", "confidence": 0-100, "reason": "<one line>"}
```

`unrelated` is a legitimate answer — an ATS sends plenty of noise (application-received
confirmations, newsletter-style updates) that isn't actually a status change; the classifier should
say so rather than being forced into one of the "real" buckets.

## Status write policy

| Signal | Confidence | Candidate count | Action |
|---|---|---|---|
| `rejection` | ≥ threshold (e.g. 85) | exactly 1 | Write `Status = Rejected` |
| `interview_invite` | ≥ threshold | exactly 1 | Write `Status = Interview Scheduled` |
| `offer` | ≥ threshold | exactly 1 | Write `Status = Offer Received` |
| `assessment` | any | any | **No status write** — no pipeline status fits "OA received" without inventing one; log only (see below) |
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

Same constraint Step 7 already worked through for GitHub Actions: no local SQLite, no reliance on
runner disk surviving between runs. Reuse that plan's resolution — **Gmail labels, not a local
watermark file.** Apply a `CareerPilot/Synced` label (via `messages().modify`, hence needing
`gmail.modify` scope rather than just `gmail.readonly`) to every message this stage has already
processed, and query `-label:CareerPilot/Synced` each run. This is stateless from the pipeline's
side — the state lives in Gmail itself, which survives independent of the runner — and it doubles
as a visible audit trail in the inbox (the user can see at a glance which emails the pipeline has
already looked at).

## Open questions / Phase 0 spike (do before any code)

1. **OAuth scope upgrade.** Confirm whether the existing `gmail_credentials.json` consent can be
   *widened* in place (re-run the consent flow with an added scope, same client) or whether it
   needs a distinct credential file. Given `send_via_gmail()`'s existing pattern degrades gracefully
   on `ImportError`/any exception, this stage should follow the same "optional, no-ops if unset"
   posture as `NOTION_SCRATCH_PAGE_ID` — a missing/unauthorized credential skips the sync, not a
   hard failure.
2. **Real sample of ATS reply emails.** Pull a handful of real rejection/interview/OA emails
   (Greenhouse, Lever, Ashby, and a couple of custom-ATS ones) and check: does the sender domain
   reliably map back to the company, or do many ATSes send from a shared domain (e.g.
   `no-reply@greenhouse.io` for every company using Greenhouse) that breaks the domain-matching half
   of "Matching," above and forces reliance on body/subject text instead? This changes how much
   weight code-level matching vs. AI classification can carry.
2b. Companion check: how many real rejection emails are vague enough ("thank you for your interest")
   that they don't name the role at all — this bounds how often the "exactly one candidate" fast
   path actually fires vs. falling to the ambiguous/AI-assisted path.
3. **Threshold calibration.** No labeled dataset exists yet for this classifier the way
   `tests/eval_data/jobs.json` does for Stage 1 scoring — Phase 0 should hand-label ~20-30 real
   emails against the signal taxonomy above and sanity-check the confidence threshold before it's
   hardcoded, the same evaluation discipline CLAUDE.md's "Testing a Change" §2 requires for any AI
   prompt.
4. **Personal inbox scope risk.** `gmail.readonly`/`gmail.modify` on a personal Gmail account reads
   (or labels) *everything* in the inbox, not just job-related mail — confirm the Gmail API query
   syntax can narrow the initial fetch tightly enough (date range + `-label:CareerPilot/Synced` +
   maybe a keyword prefilter) that this doesn't become an unbounded full-inbox scan every run.

## Notion schema additions (minimal, by design)

No new `Status` options needed — `Rejected`, `Interview Scheduled`, `Offer Received` already exist.
Two small additions, both optionally-present the same way Step 6's multi-source fields are (`_notion_write_job()`
pattern — absence doesn't break the write, the column just stays empty until added):

- `Last Email Signal` (select: `rejection`, `interview_invite`, `assessment`, `offer`,
  `recruiter_followup`, `unrelated`) — the most recent classification, for a digest section to
  filter on later.
- `Last Email Synced` (date) — when this row was last touched by the sync, mostly for debugging.

The actual email text/reasoning lives in the page body audit trail (above), not as a Notion
property — same "don't property-sprawl, cache detail in the body" precedent as the cached JD.

## Files (when implemented)

- **New:** `scripts/stage9_status_sync.py` — the stage itself: fetch unlabeled inbound mail, match,
  classify, write. Mirrors the shape of `scripts/autoapply.py`'s Layer 1 (plan/decide) vs. Layer 2
  (act) split conceptually, though there's no browser layer here — Gmail read + Notion write only.
- **Modify:** `scripts/utils.py` — a `gmail_readonly_client()` helper (parallel to
  `send_via_gmail`'s inline client construction) if reused across `stage9` and a future digest
  section; new `db_get_jobs_multi(statuses)` only if `db_get_jobs()` can't already take a list
  (check current signature before assuming a new helper is needed).
- **Modify:** `config/settings.py` — `GMAIL_SYNC_MIN_CONFIDENCE` (default candidate: 85),
  `GMAIL_SYNC_LOOKBACK_DAYS`, `STATUS_SYNC_LABEL = "CareerPilot/Synced"`.
- **Modify:** `run.py` — wire as `--stage 9`, following the existing per-stage flag pattern; decide
  whether it also joins the default `python run.py` (stages 1+4) flow or stays opt-in like stage 7
  currently is (leaning opt-in initially, given it's the first stage that can move a job to
  `Rejected` on its own).
- **Modify:** `CLAUDE.md` — new "Stage 9" section under Pipeline stages, and an amendment to the
  "Off-pipeline states... set by hand" line to document the second carve-out (Stage 2's sponsorship
  gate is the first; this would be the second).

## Verification (when implemented)

1. Unit tests mocking Gmail API responses (message list + get), following the existing
   `patch_notion_db`/`patch_ai_chat` fake pattern in `tests/conftest.py` — no live Gmail account
   needed for the default suite, same bar CLAUDE.md sets for every other stage.
2. A test proving the code-level candidate-set validator drops any AI-returned `job_id` not in the
   pre-filtered candidate list (mirrors the Step 7 acceptance criterion for its own AI ranking
   guardrail).
3. A test proving the ambiguous-match (>1 candidate) and below-threshold cases never write `Status`,
   only the audit-trail body block.
4. A test proving no downgrade path exists — feed a job already at `Interview Scheduled` an
   `unrelated`/low-confidence classification and confirm `Status` is untouched.
5. Once Phase 0's hand-labeled sample exists, run the classifier against it and report a precision
   number for the auto-write path specifically (not just overall classification accuracy) — false
   positives on the auto-write subset are the actual risk this whole design is built around.
6. Manual dry run against a real inbox with a `--dry-run` flag (same contract as Stage 7's
   `--dry-run`: real classification, zero Notion writes, so the user can eyeball what it *would*
   have done) before ever letting it write live.

## Risks

- **False positives are silent and unrecoverable in practice** — nothing else in the pipeline would
  ever notice a wrongly-`Rejected` job; digests stop showing it and the user has no reason to go
  looking. This is why the write policy above is deliberately narrower than the classification
  itself (confidence *and* unambiguous match, not confidence alone).
- **Scope creep of Gmail access** — `gmail.modify` is a broad grant on a personal inbox for what is
  functionally a read + label operation; Phase 0 question 4 exists specifically to bound the blast
  radius of the query before this is ever run unattended (e.g. via the nightly workflow).
- **No labeled eval dataset exists yet**, unlike Stage 1 scoring/Stage 2 tailoring which both have
  `tests/eval_data/` and `scripts/run_evals.py` coverage — this plan's Phase 0 explicitly includes
  building that dataset first rather than hardcoding a confidence threshold on vibes.
- **ATS shared-sender-domain risk** (Phase 0 question 2) could weaken the code-level domain match
  enough that most of the real work shifts onto the AI classifier and its guardrail, which raises
  the importance of the candidate-set validator relative to how this doc currently weights it.
- **Interacts with the nightly workflow's ephemeral runner** the same way Step 7 does — the
  label-based dedupe (not a local watermark) is required, not optional, if this ever runs in CI.

## Out of scope

- Auto-drafting a reply to any inbound email — this stage only reads and classifies; sending stays
  entirely manual (Stage 4's `--send` is the only existing send path, and it's a fixed digest, not
  a reply).
- Any status other than `Rejected` / `Interview Scheduled` / `Offer Received` being auto-written —
  `Assessment Received` as a new status is deliberately not proposed here; log-only is enough until
  real usage shows an OA-tracking gap that logging doesn't cover.
- Full thread/conversation tracking (e.g. tracking an interview-scheduling back-and-forth across
  multiple messages) — one classification per message is enough for the stated goal (status sync),
  not a general inbox-CRM feature.
