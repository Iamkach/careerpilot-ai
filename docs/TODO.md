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

## Step 9 — Evals / testing strategy (not started)

The repo has zero automated tests and no `on: pull_request`/`on: push` CI trigger today —
`.github/workflows/nightly-pipeline.yml` is the live production cron job, not a test gate.
Phased plan: a mocked pytest harness (Phase 0) covering pure functions (Phase 1 — `sources.py`
fingerprinting/filtering, `utils.py`'s `parse_json_response`), docx golden-file tests (Phase 2),
mocked AI-flow contract tests (Phase 3 — `score_jobs_batch`, tailoring fallback, InMail
truncation), and a new CI gate (Phase 4) — all free, no API keys, no live calls. A separate
opt-in Phase 5 adds a hand-labeled dataset + `scripts/run_evals.py` that hits the real Anthropic
API to track AI *judgment* quality (score accuracy, keyword recall) around prompt/model changes
— deliberately not part of CI. Also documents (without fixing) a few real gaps found during the
audit: an unclamped ATS score in `score_jobs_batch`, an inconsistent JSON-parsing fallback in
stage 3's cold-email path, missing `<ul>` wrapping in the stage 5/6 markdown→HTML converters, and
stage 6's negotiation-brief prompt claiming "web search" with no actual search tool call.

Full spec: `docs/backlog/step-9-evals-testing.md` and
`docs/refinement-plans/testing/evals-strategy.md`.
