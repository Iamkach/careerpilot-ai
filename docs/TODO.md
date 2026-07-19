# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

## Small, standalone fixes

- **Step 3 manual QA run (2026-07-18)** — added 3 real `Interested` rows (Netflix, SmithRx/
  Greenhouse, Amazon — via the scratch-note path) and ran `python run.py --ingest`. The
  self-match fix holds (no row retired against itself). But it surfaced a real bug:
  `scrape_job_urls()` only enriches `linkedin.com/jobs/view/...` URLs; all 3 non-LinkedIn URLs
  matched 0 results and were scored anyway on an empty description, landing on `Scraped` with a
  fabricated-looking score and no cached JD. Fixed: `scripts/sources.py` gained
  `enrich_job_url()` — dispatches Greenhouse/Lever/Ashby URLs to their direct per-job JSON APIs,
  everything else to a best-effort `generic_url_fetch()` HTML scrape; `ingest_interested_from_notion()`
  now partitions by actual `linkedin.com` domain (not the old digit-run regex, which
  false-matched non-LinkedIn URLs too) and never scores a job whose enrichment returned no
  description — it's left as `Interested` for the next run instead. Verified by re-running
  ingest against the same 3 rows: all landed on `Scraped` with real cached JD text and
  differentiated scores. **Known residual gap — mostly closed (2026-07-19):**
  `generic_url_fetch()` now probes for a schema.org `JobPosting` JSON-LD block before falling
  back to raw `<title>`/tag-stripped text, recovering real title/company/location even out of
  a near-empty SPA shell when that JSON-LD is present (Option A); when both that probe and the
  raw-text fallback come up short, it now also tries a headless Chromium render (Playwright,
  optional dependency) and retries the same extraction against the hydrated HTML (Option B —
  built ahead of its trigger criteria, at explicit user request, since Playwright/Chromium
  weight in the pipeline's real runtime environment hasn't been validated yet); degrades to the
  old "treat as enrichment failure" behavior if Playwright isn't installed or the render fails.
  `ingest_interested_from_notion()` also gained an `Enrichment Attempts` ceiling
  (`MAX_ENRICHMENT_ATTEMPTS`, mirroring `MAX_SCORING_ATTEMPTS`) so a permanently unfetchable URL
  gives up after N `--ingest` passes instead of retrying forever (Option D). Still open: a paid
  scrape API (Option C) as a no-new-infra alternative to B remains deferred — only worth adding
  if headless rendering proves too heavy for the actual runtime (e.g. the nightly GitHub Actions
  runner). Details in `docs/refinement-plans/sourcing/career-site-enrichment-fallback.md`.
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

