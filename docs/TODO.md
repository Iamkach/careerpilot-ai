# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

This file is scoped to code and development-blocking work only. Outstanding runtime/ops issues
(GitHub Actions secrets, CI gate, integrations — nothing that touches this repo's code) live in
`docs/RUNTIME_NOTES.md` instead.

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

- **Step 11 forkable setup — Phases 1 + 2 landed (2026-07-22).**
  `scripts/provision_notion.py` + `run.py --init` provision the "Careerpilot-ai" page + all three
  databases and env-source `NOTION_DB_ID` (hardcoded literal removed); `--setup` validates the live
  schema. **Phase 2 (identity) now done:** owner identity de-hardcoded in `config/settings.py`
  (`YOUR_NAME`/`EMAIL`/`BIO`, `TARGET_ROLES`/`COMPANIES`, `RESUME_PATH`/`RESUME_TEMPLATE_PATH` →
  `config/resume.docx`, `AI_PROVIDER` → `"claude"`) via a git-ignored `config/profile.json`
  overlay (`_load_profile()`); `--init` grew a skippable profile-wizard block + `_sync_ci_secrets()`
  (pushes `NOTION_DB_ID`/`APIFY_API_TOKEN`/provider key/`PROFILE_JSON` secrets via `gh`, or prints
  paste-ready commands); `config/ats_tokens.json` is untracked and git-ignored (identity in
  `config/profile.example.json`); `Achyuth`/`Iamkach`/DB-id references genericized across docs +
  `.claude/*`. Resume files (`config/resume.txt` / `config/resume.docx`) stay **tracked in git as
  usual** — an earlier draft that untracked them and shipped them to CI as base64-encoded secrets
  was reverted as unneeded complexity; keep them current locally and commit them like any other
  file. The nightly workflow wires `NOTION_DB_ID`/`APIFY_API_TOKEN` and materializes only
  `profile.json` from its secret. See `docs/backlog/step-11-forkable-setup.md`.

- **Nightly output retrieval (2026-07-26).** The nightly workflow's runner filesystem is
  discarded when the job ends, so every file a stage wrote to `output/` was lost — a scheduled
  run produced resumes and drafts nobody could ever read. `.github/workflows/nightly-pipeline.yml`
  now ends with an `actions/upload-artifact@v4` step (`if: always()`, `output/`, 30-day retention,
  `if-no-files-found: warn`) publishing the whole dir as one downloadable bundle per run; guarded
  by `tests/test_nightly_workflow_artifact.py`. Deliberately workflow-YAML-only — no `run.py` flag
  and no bundling code in the pipeline — so local runs are untouched by construction rather than
  by a `GITHUB_ACTIONS` env guard that could be wrong.

  **Closed (2026-07-26 follow-up).** Object storage and Notion's native file-upload API were both
  evaluated and rejected — object storage adds an account/secret a fork-friendly project shouldn't
  require, and Notion's file-upload API needs a second Notion client pinned to a newer
  `Notion-Version` (risking the `databases.query` behavior this repo's pinned `notion-client`
  version protects) for URLs that then expire after ~1 hour anyway, which would have forced stage
  4's digest to link to the Notion page instead of the file. Went with a **dedicated orphan branch**
  instead: the nightly workflow's new "Publish tailored resumes to tailored-resumes branch" step
  (`.github/workflows/nightly-pipeline.yml`, gated by a new `permissions: contents: write`) pushes
  `output/resumes/*.docx` to a `tailored-resumes` branch (self-bootstrapped on first run, additive
  only — never wipes earlier runs' files). `scripts/stage2_tailor.py`'s `_tailored_resume_link()`
  writes a `raw.githubusercontent.com` URL instead of `file://` whenever `GITHUB_ACTIONS` is set;
  local runs are byte-for-byte unaffected (same env-var-guard pattern as `_load_local_env()`). A
  raw GitHub URL doesn't expire, so stage 4's digest needed **no change**. Stage 7's
  `resolve_tailored_resume()` (`scripts/autoapply.py`) now downloads the bytes into `RESUMES_DIR`
  on the fly for a CI-tailored job instead of failing its local-file check. Guarded by
  `tests/test_nightly_workflow_publish_resumes.py`, `tests/test_stage2_resume_link.py`, and new
  cases in `tests/test_autoapply_plan.py`. Not exercised against a real nightly run/push yet — see
  the same caveat already noted for stage 7's fill path never having run live.

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md`.

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
- **docx→PDF conversion — closed (2026-07-21).** `scripts/render_docx.py` gained
  `convert_docx_to_pdf()`, shelling out to a headless LibreOffice (`soffice --headless
  --convert-to pdf`) to produce a PDF copy of the tailored resume. `autoapply_browser.py`'s
  `_resolve_upload_path()` calls it only when `_accepts_docx()` says the form's file input
  rejects `.docx`; if LibreOffice isn't installed or the conversion fails, it degrades to the
  original `pdf_only` stop (never raises — same optional-dependency contract as
  `sources._headless_fetch()`). LibreOffice is a system install, not a pip package, so nothing
  changes for an environment that doesn't have `soffice`/`libreoffice` on PATH. Untested against
  a live PDF-only form (none seen yet in the tracker); unit-tested with a mocked `subprocess.run`
  in `tests/test_render_docx.py` and `tests/test_autoapply_browser_pdf_fallback.py`.
- **Phase 3 (deliberate submit) deferred by choice** pending real use of the fill path. The
  research argues against rushing it: ATSes now score application velocity and flag high-volume
  submitters as low-intent before a human reads the application, so the marginal value of
  automating the final click is lower than it looks.
- **Phase 4 (Workday/agentic long tail) not started.** Workday runs a separate tenant per
  company and its resume parser fails ~30% of the time; account provisioning is the real cost.
  **Related, written down 2026-07-21:** `FILLABLE_CHANNELS = {"greenhouse", "lever"}` is the only
  gate Layer 2 checks — Ashby, Workday, and any custom company careers page (`unknown` channel,
  e.g. a site like Netflix's own) get Layer 1's answer sheet only, never a browser fill, today.
  LinkedIn/Indeed are excluded *by rule* (ToS/detection) and are out of scope for this; Ashby/
  Workday/custom are just not built yet. Deferred — not queued, see trigger criteria — in
  `docs/refinement-plans/auto-apply/ashby-workday-custom-fill.md`.
- **Schema migration must be run once** before stage 7 can transition anything:
  `python scripts/setup_notion_schema.py --apply` adds the six new `Status` options and the four
  new properties. (`databases.update` can extend the schema even though `pages.update` silently
  ignores an unknown select option — so only the per-page write is unscriptable.) Idempotent and
  dry-run by default. If skipped, `db_update_status_verified()` fails loudly rather than silently
  no-opping, so it surfaces on first run rather than corrupting state.

Full spec + the research findings that shaped the design:
`docs/backlog/step-10-auto-apply-subsystem.md` §11.

