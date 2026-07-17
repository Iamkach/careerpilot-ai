# Recorded AI responses (Step 9, Phase 3a)

Real Claude Code subscription responses to the exact prompts `scripts/stage1_scrape.py`,
`scripts/stage2_tailor.py`, and `scripts/stage3_outreach.py` send, recorded via
`tests/record_ai_responses.py`. Phase 3b's mocked contract tests replay these instead of
hand-authored canned JSON — see the 2026-07-16 incident writeup in
`docs/backlog/step-9-evals-testing.md` for why a hand-written mock can't stand in for this
(it's well-formed JSON by construction and can never reproduce truncation/near-truncation
behavior under a real large-batch prompt).

## Regenerating

```
python tests/record_ai_responses.py            # all scenarios
python tests/record_ai_responses.py --only stage1
python tests/record_ai_responses.py --list      # list scenario names without running
```

Requires the Claude Code CLI installed and logged in (`claude /login`). Runs entirely on the
subscription (`FAST_PROVIDER=QUALITY_PROVIDER=claude_code`, set by the script itself before
`config.settings` is imported) — no `ANTHROPIC_API_KEY`/metered cost, and no effect on any
other env var. Re-run manually whenever a prompt template or `_SCORE_CHUNK_SIZE` changes
meaningfully enough that a stale recording would stop reflecting real model behavior. This
script is never invoked by `run.py`, `tests.yml`, or `nightly-pipeline.yml`.

## Layout

```
stage1_score/     score_jobs_batch / _score_jobs_chunk (scripts/stage1_scrape.py)
  batch_001.json                   1 job, single chunk
  batch_020.json                   20 jobs — exactly one chunk (_SCORE_CHUNK_SIZE boundary)
  batch_021_chunk0.json            21 jobs — chunk 1/2 (20 jobs)
  batch_021_chunk1.json            21 jobs — chunk 2/2 (1 job)
  batch_050_chunk*.json            50 jobs — 3 chunks
  batch_100_chunk*.json            100 jobs — 5 chunks
  oversized_single_call_150.json   _score_jobs_chunk called directly with 150 jobs, bypassing
                                    score_jobs_batch's chunking — reproduces the 2026-07-16
                                    incident's shape (one oversized call) directly
  empty_garbled_description.json   one empty JD + one garbled/non-language JD in one chunk

stage2_tailor/     _tailor_resume_single / tailor_resumes_batch (scripts/stage2_tailor.py)
  single_normal.json               normal-size missing_keywords hint (2 keywords)
  single_huge_keyword_hint.json    intentionally huge (80-entry) missing_keywords hint
  batch_normal_3jobs.json          tailor_resumes_batch, 3 jobs in one call

stage3_outreach/   draft_cold_emails_batch / draft_inmail_batch (scripts/stage3_outreach.py)
  cold_email_batch_5.json          5 jobs in one call
  inmail_batch_5.json              5 jobs in one call
```

## Fixture JSON shape

```jsonc
{
  "scenario": "human-readable description of what this call exercised",
  "function": "score_jobs_batch/_score_jobs_chunk",
  "recorded_at": "2026-07-16T12:34:56.789012+00:00",
  "provider": "claude_code",
  "model": "sonnet",
  "input_summary": { "job_count": 20, "chunk_index": 0, "chunk_count": 1 },
  "raw_response": "<exact text returned by the model — the fixture Phase 3b tests replay>",
  "parse_success": true,
  "parse_error": null
}
```

`parse_success`/`parse_error` come from running the *same* `parse_json_response()` the
production code uses against `raw_response` at recording time — a `false` here is itself a
real finding (a case where the real model produced something the parser can't handle), not a
recording bug, and Phase 3b should have a test asserting the production code degrades
correctly (`scored: False`, batch-parse-fails-fall-back-to-per-job, etc.) on exactly that
fixture.

## Note: `oversized_single_call_150.json` did NOT reproduce truncation

All 19 recordings above parsed successfully, including `oversized_single_call_150` (150 jobs,
one call, no chunking — the exact shape of the 2026-07-16 incident). This is expected, not a
recording bug: `_chat_claude_code` goes through the Agent SDK's one-shot `query()`
(`scripts/utils.py::_sdk_text`), which has **no `max_tokens` knob** — the incident's actual
cause was the *metered* API's `max_tokens=4096` cap (`_chat_claude`), which the subscription
path doesn't share. So this fixture is a legitimate "large batch, real model, no chunking"
recording, but it cannot stand in for the truncation failure mode itself. Phase 3b's
regression test for the incident (a chunk-level failure must only blank out that chunk, not
the whole batch — see the story's Verification section) should keep using a **hand-authored**
truncated/malformed JSON string for that specific case, per Phase 3b's allowance for "a small
number of hand-authored edge cases for branches no recording happened to hit."
