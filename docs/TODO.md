# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

## Small, standalone fixes

- **Step 3 manual QA never run** — add a real `Interested` row with a live LinkedIn URL, run
  `python run.py --ingest`, confirm it lands on `Scraped` with a real score and cached JD (not
  silently retired). Re-run ingest twice to confirm the `existing_urls` snapshot doesn't treat
  the first run's output as a duplicate of itself.
- **Known gaps characterized (not fixed) by the Step 9 test suite** — locked in by
  characterization tests so a future fix has a single place to update, not blocking anything
  today: `score_jobs_batch`'s `int(entry.get("score", 0))` has no bounds clamping, so a
  hallucinated score of `150` or `-10` passes through uncaught (`scripts/stage1_scrape.py`);
  stage 3's `_draft_cold_email_single` fallback does ad-hoc
  `raw.strip().strip("```json").strip("```")` instead of reusing `parse_json_response`, unlike
  every other AI-parsing path in the codebase; the stage 5/6 markdown→HTML converters never wrap
  consecutive `<li>` lines in `<ul>`/`<ol>`, producing invalid list HTML; `stage6_negotiate.py`'s
  `generate_negotiation_brief` module docstring claims "Claude + web search" but no actual
  search tool is called — comp numbers come from the model's own training knowledge and can go
  stale silently (`scripts/run_evals.py --comp-check` is the manual spot-check for this one).

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.

