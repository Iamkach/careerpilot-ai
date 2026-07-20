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

## Open for review — deferred out of the PR #11 review fixes (2026-07-19)

Both surfaced reviewing PR #11 (`feature/god-speed` → `main`) and were deliberately **not**
actioned in commit `7d460ba`, which fixed the other ten findings. Neither is a one-line
cleanup; both want a decision before any code moves. Nothing here is committed to yet.

- **`_prop_number()` conflates "absent" with a real `0`** (`scripts/utils.py`). It returns
  `(props.get(name) or {}).get("number") or 0`, so a row with an empty `ATS Match Score` and a
  row genuinely scored `0` read back identically. That sits at odds with the contract the rest
  of stage 1 is built on — `score_jobs_batch()` returns `scored: False` rather than fabricate a
  number, and `_unscored()` exists specifically so a missing score never becomes a numeric one.
  Once it passes through `_page_to_job()`, that distinction is gone anyway.
  **Why it wasn't just fixed:** returning `None` is a regression, not a fix. `db_get_jobs()`
  sorts on the value, `rescore_retry_jobs()` and stage 2 compare it against `MIN_ATS_SCORE` /
  `MIN_TAILORED_ATS_SCORE`, and the same helper backs `Scoring Attempts` / `Enrichment
  Attempts` / `Applicant Count`, where `0` is the correct default and `None` would break the
  `(x or 0) + 1` increments. A real fix needs a separate nullable reader used only at the
  score call sites, plus a decision on what a `None` score means to each consumer (skip? sort
  last? treat as unscored and re-queue?).
  **Open questions:** is the ambiguity actually causing observable harm today, or is it
  theoretical? Does any real row sit at a legitimate `0`, or does `MIN_ATS_SCORE` mean a 0 is
  always dropped before it's written? Cheapest correct fix might be at the *write* side
  (never write `0`, write nothing) rather than the read side.

- **`tests.yml` has never actually run** — every Actions run on `feature/god-speed` is
  `startup_failure` at 0s with no job name (runs `29711371199` pull_request, `29711381997`
  push). Both workflow files parse fine and the suite is green locally (212 passed), so this
  is environmental, not a code defect: most likely Actions disabled for the repo, or a
  spending/billing limit on the private repo — the only check reporting on the PR is a stale
  Supabase Preview integration, itself vestigial now that `sync_notion_to_supabase()` is a
  no-op. Until it's resolved, "CI gate on every PR/push" is a claim the repo doesn't hold up,
  and the local `pytest` run is the only evidence the suite passes.
  **Needs a human with repo settings access:** check Settings → Actions and the billing page.
  Separately, decide whether to remove the Supabase integration.

- **Other `run.py` routines still traceback on a failed Notion read** — `--ingest` now reports
  a clean message and exits 1 (commit below), but `--retry-only`, `--stage 2/3/4` and
  `--evaluate` reach `db_get_jobs()` → `_query_db()`, which has always propagated. **This is
  pre-existing, not introduced by the PR #11 review fixes** — `db_get_jobs()` never caught. The
  question is whether to give every CLI entry point the same clean-message + non-zero-exit
  treatment `ingest_routine()` now has, or leave the raw traceback (which at least exits
  non-zero, so the nightly workflow does fail correctly either way). Not actioned because it
  changes the exit behavior of five more CLI paths, which is a decision rather than a fix.

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.

