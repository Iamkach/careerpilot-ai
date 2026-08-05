# Verification (when implemented)

1. Unit tests mocking Gmail API responses (message list + get), following the existing
   `patch_notion_db`/`patch_ai_chat` fake pattern in `tests/conftest.py` — no live Gmail account
   needed for the default suite, same bar CLAUDE.md sets for every other stage.
2. A test proving the code-level candidate-set validator drops any AI-returned `job_id` not in the
   pre-filtered candidate list.
3. A test proving the ambiguous-match (>1 candidate) and below-threshold cases never write
   `Status`, only the audit-trail body block.
4. A test proving no downgrade path exists — feed a job already at `Interview Scheduled` an
   `unrelated`/low-confidence classification and confirm `Status` is untouched.
5. Once Phase 0's hand-labeled sample exists, run the classifier against it and report a precision
   number for the auto-write path specifically (not just overall classification accuracy) — false
   positives on the auto-write subset are the actual risk this whole design is built around.
6. Manual dry run against a real inbox with a `--dry-run` flag (same contract as Stage 7's
   `--dry-run`: real classification, zero Notion writes, so the user can eyeball what it *would*
   have done) before ever letting it write live.
