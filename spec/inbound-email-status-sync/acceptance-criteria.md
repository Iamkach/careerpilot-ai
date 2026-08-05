# Acceptance criteria

- [ ] Phase 0 spike (OAuth scope check, real ATS reply sample, threshold calibration — see plan.md)
      completed before any code is written.
- [ ] The code-level candidate-set validator drops any AI-returned `job_id` not present in the
      pre-filtered candidate list.
- [ ] The ambiguous-match (>1 candidate) and below-threshold cases never write `Status`, only the
      audit-trail body block.
- [ ] No downgrade path exists — feeding a job already at `Interview Scheduled` an
      `unrelated`/low-confidence classification leaves `Status` untouched.
- [ ] Once Phase 0's hand-labeled sample exists, the classifier reports a precision number for the
      auto-write path specifically (not just overall classification accuracy) — false positives on
      the auto-write subset are the actual risk this design is built around.
- [ ] A `--dry-run` flag exists (same contract as Stage 7's: real classification, zero Notion
      writes) and has been run against a real inbox before this stage is ever allowed to write live.
- [ ] A missing/unauthorized Gmail credential skips the sync (no-op), never a hard failure —
      matching the `NOTION_SCRATCH_PAGE_ID`-style optional-feature posture.
