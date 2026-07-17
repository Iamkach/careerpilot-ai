# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

## Small, standalone fixes

- **Step 3 manual QA never run** — add a real `Interested` row with a live LinkedIn URL, run
  `python run.py --ingest`, confirm it lands on `Scraped` with a real score and cached JD (not
  silently retired). Re-run ingest twice to confirm the `existing_urls` snapshot doesn't treat
  the first run's output as a duplicate of itself.

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.

## Step 9 — Evals / testing strategy (Phases 0-4 done, Phase 5 not started)

`.github/workflows/tests.yml` now runs the full mocked pytest suite (129 tests, ~1.5s) on
every `pull_request`/`push`, with no API keys and no Claude Code login required anywhere in it
— separate from `.github/workflows/nightly-pipeline.yml`, the live production cron job, which
is untouched. Landed: pure-function unit tests (Phase 1 — `sources.py` fingerprinting/filtering,
`utils.py`'s `parse_json_response`), docx golden-file tests (Phase 2), a one-time real-call
recording pass via Claude Code whose output lives under `tests/fixtures/recorded_ai_responses/`
(Phase 3a, never re-run in CI), and mocked AI-flow contract tests seeded from those recordings
(Phase 3b — `score_jobs_batch`'s chunk-boundary isolation, tailoring fallback, InMail
truncation). A separate opt-in Phase 5 would add a hand-labeled dataset + `scripts/run_evals.py`
that hits the real Anthropic API to track AI *judgment* quality (score accuracy, keyword
recall) around prompt/model changes — deliberately not part of CI, and not yet built. The
suite also documents (without fixing) a few real gaps found during the audit: an unclamped ATS
score in `score_jobs_batch`, an inconsistent JSON-parsing fallback in stage 3's cold-email path,
missing `<ul>` wrapping in the stage 5/6 markdown→HTML converters, and stage 6's
negotiation-brief prompt claiming "web search" with no actual search tool call.

Full spec: `docs/backlog/step-9-evals-testing.md` and
`docs/refinement-plans/testing/evals-strategy.md`.
