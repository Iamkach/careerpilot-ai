# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

## Small, standalone fixes

- **Step 3 manual QA never run** — add a real `Interested` row with a live LinkedIn URL, run
  `python run.py --ingest`, confirm it lands on `Scraped` with a real score and cached JD (not
  silently retired). Re-run ingest twice to confirm the `existing_urls` snapshot doesn't treat
  the first run's output as a duplicate of itself.
- ~~**Known gaps characterized (not fixed) by the Step 9 test suite**~~ — fixed:
  `score_jobs_batch` now clamps `int(entry.get("score", 0))` to `[0, 100]`
  (`scripts/stage1_scrape.py`); stage 3's `_draft_cold_email_single` fallback now reuses
  `parse_json_response` instead of ad-hoc `str.strip()` fence-trimming, so it recovers JSON from
  a prose-wrapped response like every other AI-parsing path; the stage 5/6 markdown→HTML
  converters now wrap consecutive `<li>` lines in `<ul>`/`</ul>` via the shared
  `scripts/utils.wrap_consecutive_li()`; `stage6_negotiate.py`'s module docstring no longer
  claims "Claude + web search" — it now says comp numbers come from the model's training
  knowledge only and can go stale, pointing at `scripts/run_evals.py --comp-check` as the manual
  spot-check.

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.

