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

## Open for review — deferred out of the PR #11 review fixes (2026-07-19)

These surfaced reviewing PR #11 (`feature/god-speed` → `main`) and were deliberately **not**
actioned in commit `7d460ba`, which fixed the other ten findings. **Update 2026-07-21:** the
`run.py` traceback item and `_prop_number()` item are now fixed (see `docs/CHANGELOG.md`); the
`tests.yml` CI item is **still open** and needs a human with repo Settings access — it is not a
code change.

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

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.

## Step 10 — Auto-Apply subsystem (Phases 1–2 landed 2026-07-19)

Stage 7 (`scripts/autoapply.py` + `scripts/autoapply_browser.py`, wired as `run.py --stage 7`
/ `--stage 7 --fill`) now plans every application answer, gates on anything it can't answer
confidently, emits an HTML answer sheet, and optionally pre-fills the live form in Chromium.
**It never submits** — `WRITABLE_STATUSES` excludes `Applied` on purpose, and the browser
module contains no submit code path at all. Confirmed during research: no candidate-usable
submit API exists (Greenhouse's endpoint authenticates as the *employer*), so this is
irreducibly a browser problem.

**Open residual gaps:**

- **Live schema fetch validated once; address/attachment mapping gaps closed (2026-07-21); fill
  path still not run live.** The Greenhouse `?questions=true` fetch was run for the first time
  against a real tracker job (SmithRx, "Senior Staff Automation Engineer") and **worked** — 25
  fields returned and mapped, confirming the core Phase-1 read premise on a live board. It
  surfaced two mapping gaps, both now fixed: (a) the structured-address block (`Legal First/Last
  Name`, `Address Line 1/2`, `City`, `State`, `Country`, `Zip Code`, `Address Type`) is now
  captured by a new `"address"` section in the `run.py --setup-profile` wizard, persisted to
  `config/application_profile.json` alongside the existing sections, exposed as
  `APPLICATION_ADDRESS` in `config/settings.py`, and matched via new `_LABEL_RULES` keyword
  entries in `scripts/autoapply.py` (label text, not field `name` — Greenhouse's `name`
  attributes for these fields are opaque, unlike the confirmed-stable `first_name`/`last_name`/
  `email`/`phone` in `_FIELD_MAP`); legal name is deliberately independent of the resume/outreach
  display name, since a candidate's legal and preferred names can differ. (b) The dual-field
  attachment quirk (Greenhouse emits an `input_file` + a `textarea` under one label, e.g.
  "Resume/CV") is fixed in `build_application_plan()`: the `textarea` sibling of an already-
  resolved attachment field now mirrors that field's resolution instead of being independently
  evaluated as an unresolved free-text question, order-independent (works whichever field is
  listed first). Covered by new tests in `tests/test_autoapply_profile.py` and
  `tests/test_autoapply_plan.py` (388 passed). **The Layer-2 fill path has still never run
  against a live form** (only the bundled sample and a local `file://` fixture) — re-running the
  plan against the SmithRx job (or another live Greenhouse posting) to confirm the blocker count
  actually drops is the natural next validation step, then exercising the fill path itself. Note
  the tracker currently holds only **one** Greenhouse row (413 LinkedIn / 90 Indeed / 4 unknown
  of 508), both of which are manual-only — so weighting `ENABLED_SOURCES` toward ATS boards is a
  prerequisite for Stage 7 to matter at volume.
- **No docx→PDF conversion.** Stage 2 emits `.docx` only, and a converter needs LibreOffice or
  Word. A PDF-only upload field currently stops as `pdf_only` and asks the human to convert.
  Only worth building if PDF-only forms turn out to be common in practice.
- **Phase 3 (deliberate submit) deferred by choice** pending real use of the fill path. The
  research argues against rushing it: ATSes now score application velocity and flag high-volume
  submitters as low-intent before a human reads the application, so the marginal value of
  automating the final click is lower than it looks.
- **Phase 4 (Workday/agentic long tail) not started.** Workday runs a separate tenant per
  company and its resume parser fails ~30% of the time; account provisioning is the real cost.
- **Schema migration must be run once** before stage 7 can transition anything:
  `python scripts/setup_notion_schema.py --apply` adds the six new `Status` options and the four
  new properties. (`databases.update` can extend the schema even though `pages.update` silently
  ignores an unknown select option — so only the per-page write is unscriptable.) Idempotent and
  dry-run by default. If skipped, `db_update_status_verified()` fails loudly rather than silently
  no-opping, so it surfaces on first run rather than corrupting state.

Full spec + the research findings that shaped the design:
`docs/backlog/step-10-auto-apply-subsystem.md` §11.

