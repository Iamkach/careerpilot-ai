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
4. **Phase 3 — mocked AI-flow contract tests (M).** With AI calls monkeypatched to canned
   responses, test the plumbing (not AI judgment quality) around `score_jobs_batch`,
   `rescore_retry_jobs`'s give-up boundary, `tailor_resumes_batch`/`_tailor_resume_single`'s
   batch-to-single fallback, `verify_tailored_score`'s empty-result synthesis, and stage 3's
   InMail truncation boundaries. Includes documented (not fixed) characterization tests for the
   unclamped-ATS-score gap and the cold-email fallback's ad-hoc JSON stripping.
5. **Phase 4 — CI gate live (XS).** `tests.yml` runs the full mocked suite on every PR/push, no
   API keys required anywhere in it.
6. **Phase 5 — AI-quality eval layer (M, not part of CI).** Hand-labeled dataset (8-12 real jobs
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
| 3 — mocked AI-flow contract tests | M | Phase 0 |
| 4 — CI gate live | XS | Phases 0-3 |
| 5 — AI-quality eval dataset + script | M | Phases 0-4 |

## Verification

- `pytest` (Phases 0-3) passes locally and in the new `tests.yml` workflow with no
  `ANTHROPIC_API_KEY`/`NOTION_API_KEY`/`APIFY_API_TOKEN` set or needed.
- `nightly-pipeline.yml` is untouched and continues to run the live pipeline exactly as before.
- `scripts/run_evals.py` (Phase 5) is never invoked by `run.py`, `--evaluate`, or any CI workflow
  — confirm by grepping for its name outside its own file and this doc.

## Non-goals

Not fixing the bugs/inconsistencies this audit surfaced while writing tests (unclamped ATS score,
cold-email JSON-parsing inconsistency, missing `<ul>` wrapping, stage 6's no-actual-web-search
prompt) — those are characterized, not fixed, and tracked as a follow-up note in
`docs/TODO.md`. Not adding real-API calls to the CI-gated suite. See the source plan for full
rationale and file:function references.
