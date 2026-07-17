# Step 9 — Evals / testing strategy

**Priority:** P2 — no functional gap for users, but the repo currently has zero automated gate
before code reaches `main`, and every stage script now carries enough retry/fallback/coercion
logic (Steps 2 and 5's reliability work) that manual spot-checks no longer cover it reliably.
**Depends on:** none — additive; can start immediately alongside Step 7 or Step 8.
**Size:** M-L, phased (see table below) — each phase is independently shippable.
**Source plan:**
[`refinement-plans/testing/evals-strategy.md`](../refinement-plans/testing/evals-strategy.md)
(full spec — this story is a condensed implementation checklist)

## Context

Steps 0-6 plus the Step 2/Step 5 reliability passes shipped with no `pytest` (or any test
framework) in `requirements.txt`, no `conftest.py`/`pytest.ini`, no `tests/` directory, and no
`on: pull_request`/`on: push` CI trigger — `.github/workflows/nightly-pipeline.yml` is the live
production cron job itself, and its only "verification" step (`python run.py --setup`) is a
config sanity check, not a test. This story adds a phased test/eval harness without touching any
production stage logic.

**2026-07-16 incident, and why it changes Phase 3's plan:** `stage1_scrape.score_jobs_batch` sent
every candidate from a scrape in a single AI call, capped at the default 4096 output tokens. A
normal day's scrape produced 100+ candidates; the JSON reply for that many jobs truncated
mid-array, parsing failed for the *whole* batch, and all 104 jobs landed in Notion as `Retry` with
a blank ATS score (`scored: False` is the correct response to a parse failure — the bug was letting
one call cover a batch large enough to blow the token cap in the first place). Fixed by chunking
(`_SCORE_CHUNK_SIZE = 20` in `score_jobs_batch`/`_score_jobs_chunk`) plus an explicit `max_tokens`.
The reason this matters for this story: Phase 3 as originally scoped (hand-authored canned
JSON strings fed to a monkeypatched `ai_chat`) **cannot catch this class of bug by construction** —
a hand-written mock is well-formed JSON by definition, so it can never reproduce what a real model
does under a large-batch/near-truncation prompt. Phase 3 below is restructured into a 3a
(real-call recording pass via Claude Code) that produces the fixtures, and a 3b (mocked contract
tests) that consumes them, so the mocks are seeded from observed real behavior instead of guessed
from imagination.

## What to do

1. **Phase 0 — harness + CI wiring (S).** New `requirements-dev.txt` (`pytest`, `pytest-mock`);
   new `tests/conftest.py` with a fake `ai_chat`/`ai_chat_blocks` fixture and a fake in-memory
   Notion layer (`db_*` functions from `scripts/utils.py` monkeypatched); a shared sample
   resume/job fixture. New `.github/workflows/tests.yml` on `pull_request` + `push`, separate
   from `nightly-pipeline.yml`.
2. **Phase 1 — pure-function unit tests (S).** `scripts/sources.py` (`job_fingerprint`,
   `collapse_by_fingerprint`, `title_matches_targets`, `_is_fresh`, `_to_iso_date`,
   `_parse_salary`); `scripts/utils.py` (`matches_company_list`/token-matching helpers,
   `parse_json_response` — the highest-leverage single target in the repo);
   `scripts/stage2_tailor.py`'s `_sponsorship_gate`; `scripts/stage6_negotiate.py`'s
   `get_company_type`; the markdown→HTML regex converters in stage 5/6 (including a
   characterization test for the known missing-`<ul>`-wrapping gap).
3. **Phase 2 — docx golden-file tests (S).** `scripts/render_docx.py`'s `extract_docx_text` /
   `apply_docx_edits` against a fixture `.docx` — exact text extraction, exact post-edit output,
   the unmatched-edit case, plus characterization tests for the run-collapsing formatting-loss
   and same-paragraph double-edit clobber edge cases.
4. **Phase 3a — real-call recording pass via Claude Code (S, not part of CI, run once up front).**
   Before writing a single canned-JSON mock, run the actual stage functions (`score_jobs_batch` /
   `_score_jobs_chunk`, `tailor_resumes_batch`/`_tailor_resume_single`, stage 3's outreach draft
   call) with `AI_PROVIDER="claude_code"` — free under the subscription, no metered cost — against
   realistic and adversarial inputs: batch sizes of 1, 20 (the new chunk boundary), 21, 50, and
   100+ jobs; a deliberately oversized single chunk to reproduce the truncation failure mode
   directly instead of trusting the fix in isolation; a job whose description is empty/garbled; and
   a resume-tailoring call with an intentionally huge `missing_keywords` hint list. Save each raw
   response (and, where truncated/malformed, the raw text as-is) under
   `tests/fixtures/recorded_ai_responses/`. This is a one-time-per-drift recording pass, re-run
   manually whenever a prompt or chunk size changes meaningfully enough that stale fixtures would
   stop reflecting real model behavior — not a step that runs on every PR.
5. **Phase 3b — mocked AI-flow contract tests, seeded from Phase 3a (M).** With `ai_chat`/
   `ai_chat_blocks` monkeypatched to return the *recorded* responses from Phase 3a (plus a small
   number of hand-authored edge cases for branches no recording happened to hit), test the plumbing
   (not AI judgment quality) around `score_jobs_batch`, the chunking boundary itself (a chunk-level
   failure — mock `_score_jobs_chunk` to raise on one chunk — must only blank out that chunk's jobs,
   never the whole batch), `rescore_retry_jobs`'s give-up boundary, `tailor_resumes_batch`/
   `_tailor_resume_single`'s batch-to-single fallback, `verify_tailored_score`'s empty-result
   synthesis, and stage 3's InMail truncation boundaries. Includes documented (not fixed)
   characterization tests for the unclamped-ATS-score gap and the cold-email fallback's ad-hoc JSON
   stripping.
6. **Phase 4 — CI gate live (XS).** `tests.yml` runs the full mocked suite (Phase 3b, built on
   Phase 3a's recordings) on every PR/push, no API keys and no Claude Code login required anywhere
   in it — Phase 3a's recording pass never runs in CI, only its saved output does.
7. **Phase 5 — AI-quality eval layer (M, not part of CI).** Hand-labeled dataset (8-12 real jobs
   + resume, expected score range + keyword set) and a standalone opt-in
   `scripts/run_evals.py` (outside `run.py`'s entry point) that hits the real Anthropic API and
   reports score-hit-rate / keyword-recall / tailored-ATS-delta. Run manually around prompt or
   `QUALITY_MODEL` changes. Also the intended home for periodically re-checking stage 6's
   comp-benchmark prompt, which the source plan flags as prose from the model's own knowledge
   despite the module docstring's "Claude + web search" claim — no actual search tool is called.

| Phase | Size | Depends on |
|---|---|---|
| 0 — harness + CI wiring | S | none |
| 1 — pure-function unit tests | S | Phase 0 |
| 2 — docx golden-file tests | S | Phase 0 |
| 3a — real-call recording pass (Claude Code) | S | Phase 0 |
| 3b — mocked AI-flow contract tests | M | Phase 3a |
| 4 — CI gate live | XS | Phases 0-3b |
| 5 — AI-quality eval dataset + script | M | Phases 0-4 |

## Verification

- `pytest` (Phases 0-2, 3b) passes locally and in the new `tests.yml` workflow with no
  `ANTHROPIC_API_KEY`/`NOTION_API_KEY`/`APIFY_API_TOKEN` set or needed and no Claude Code login
  required — CI only ever reads Phase 3a's saved fixture files, never re-records them.
- Phase 3a's recording pass runs manually (via a logged-in Claude Code session), is never invoked
  by `tests.yml`, `run.py`, or `nightly-pipeline.yml`, and its output lands only under
  `tests/fixtures/recorded_ai_responses/`.
- A dedicated regression test exists for the 2026-07-16 incident: a batch above
  `_SCORE_CHUNK_SIZE` is split into multiple `_score_jobs_chunk` calls, and one chunk raising
  leaves every *other* chunk's jobs correctly scored (not blanked out with it).
- `nightly-pipeline.yml` is untouched and continues to run the live pipeline exactly as before.
- `scripts/run_evals.py` (Phase 5) is never invoked by `run.py`, `--evaluate`, or any CI workflow
  — confirm by grepping for its name outside its own file and this doc.

## Non-goals

Not fixing the bugs/inconsistencies this audit surfaced while writing tests (unclamped ATS score,
cold-email JSON-parsing inconsistency, missing `<ul>` wrapping, stage 6's no-actual-web-search
prompt) — those are characterized, not fixed, and tracked as a follow-up note in
`docs/TODO.md`. Not adding real-API/Claude-Code calls to the CI-gated suite — Phase 3a is a manual,
opt-in recording step whose *output* feeds CI, not a step CI ever re-runs itself. See the source
plan for full rationale and file:function references.
