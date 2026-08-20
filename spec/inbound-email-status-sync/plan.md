# Plan

## Matching: email → job row

Restrict the candidate set with code before any AI call:

1. Pull the in-flight snapshot: `db_get_jobs(status)` for each of `Applied`, `Outreach Sent`,
   `Interview Scheduled` (reuse the existing helper — no new Notion read primitive needed).
2. For each unprocessed inbound message (see constraints.md's dedupe rule), narrow to jobs whose
   `Company` fuzzy-matches the sender's domain or display name. Reuse `job_fingerprint()`'s
   normalization idea (`scripts/sources.py`) rather than inventing new string-matching — strip
   legal suffixes, lowercase, compare.
3. If that narrows to **exactly one** candidate job → high-confidence match, proceed to
   classification with that job pinned (no AI guessing needed for *which* job).
4. If it narrows to **more than one** (e.g. two open reqs at the same company) → pass all
   candidates to the AI classifier and let it pick using subject-line/body context (job title
   keywords), but the code-level validator still rejects any answer whose `job_id` isn't in that
   candidate set — the AI narrows among knowns, it doesn't invent a new match.
5. If it narrows to **zero** → no update, no AI call. Not every inbound email is job-related; most
   won't match anything, and that's the expected common case, not an error.

This mirrors the communications-subsystem spec's own guardrail almost exactly ("validate every
returned `idx` against the input set and drop anything referencing a name/email not present in it").

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
   `no-reply@greenhouse.io` for every company using Greenhouse) that breaks the domain-matching
   half of "Matching," above and forces reliance on body/subject text instead? This changes how much
   weight code-level matching vs. AI classification can carry.
   Companion check: how many real rejection emails are vague enough ("thank you for your interest")
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

## Risks

- **False positives are silent and unrecoverable in practice** — nothing else in the pipeline would
  ever notice a wrongly-`Rejected` job; digests stop showing it and the user has no reason to go
  looking. This is why the write policy in constraints.md is deliberately narrower than the
  classification itself (confidence *and* unambiguous match, not confidence alone).
- **Scope creep of Gmail access** — `gmail.modify` is a broad grant on a personal inbox for what is
  functionally a read + label operation; Phase 0 question 4 exists specifically to bound the blast
  radius of the query before this is ever run unattended (e.g. via the nightly workflow).
- **No labeled eval dataset exists yet**, unlike Stage 1 scoring/Stage 2 tailoring which both have
  `tests/eval_data/` and `scripts/run_evals.py` coverage — Phase 0 explicitly includes building
  that dataset first rather than hardcoding a confidence threshold on vibes.
- **ATS shared-sender-domain risk** (Phase 0 question 2) could weaken the code-level domain match
  enough that most of the real work shifts onto the AI classifier and its guardrail, which raises
  the importance of the candidate-set validator relative to how this doc currently weights it.
- **Interacts with the nightly workflow's ephemeral runner** the same way the communications
  subsystem does — the label-based dedupe (not a local watermark) is required, not optional, if
  this ever runs in CI.
