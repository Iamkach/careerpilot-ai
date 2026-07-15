# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

## Small, standalone fixes

- **Step 3 manual QA never run** — add a real `Interested` row with a live LinkedIn URL, run
  `python run.py --ingest`, confirm it lands on `Scraped` with a real score and cached JD (not
  silently retired). Re-run ingest twice to confirm the `existing_urls` snapshot doesn't treat
  the first run's output as a duplicate of itself.

- **Add the `Missing Keywords` column to the live Notion DB** — code now writes/reads a
  `Missing Keywords` (rich_text) property (Stage 1's `score_jobs_batch()` output, fed into
  Stage 2's tailoring prompt as a hint, and a post-tailor `ATS: before → after` re-score gated
  by `MIN_TAILORED_ATS_SCORE`), but per the "add by hand" pattern documented in CLAUDE.md for
  optional columns, the property must be added to the live DB manually — until then the write
  is silently skipped (no crash) and Stage 2 just has no Stage-1 hint to work from.

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.

## Step 8 — Runtime `--ai-mode` flag (not started)

Add `run.py --ai-mode {metered,hybrid,subscription}` so AI provider routing
(`FAST_PROVIDER`/`QUALITY_PROVIDER`) can be picked per invocation instead of only via config
edits or env vars (today only the nightly workflow overrides the default). XS-sized, no
dependencies.

Full spec: `docs/backlog/step-8-runtime-ai-mode-flag.md` and
`docs/refinement-plans/ai-provider/runtime-ai-mode-flag.md`.
