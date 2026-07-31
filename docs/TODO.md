# TODO — standalone fixes and reminders

This file is scoped to **small, standalone** code/development-blocking items only — quick fixes
and reminders for the next execution. It is not an index of open roadmap stories: every
step-numbered story (its problem statement, design decisions, and open residual gaps) lives
entirely in its own `docs/backlog/step-N-*.md` file — see `docs/backlog/README.md` for the current
list. See `docs/CHANGELOG.md` for what's already landed.

Outstanding runtime/ops issues (GitHub Actions secrets, CI gate, integrations — nothing that
touches this repo's code) live in `docs/RUNTIME_NOTES.md` instead.

## Small, standalone fixes

- **Step 11 fresh-fork verification (2026-07-30).** Step 11 (`--init` wizard + Notion
  provisioning + profile.json de-personalization) is fully implemented and merged via PR #19 —
  but into `feature/step-10-auto-apply`, **not into GitHub's `main`**, which is currently 36
  commits behind this branch stack (Steps 7/10/12/13/14/15 all live only in that unmerged chain).
  Don't treat "implemented" as "shippable to users" until that stack actually lands on `main`. The
  one thing never actually run, independent of that: a fresh-fork dry run confirming `--init`
  end-to-end (Notion provisioning + profile wizard + `gh` secret sync) works for someone who isn't
  the original owner.

- **Step 3 manual QA run (2026-07-18) — closed except Option C.** Manually ingesting 3 real
  `Interested` rows surfaced a bug (non-LinkedIn URLs scored on a blank JD); fixed via
  `enrich_job_url()`/`generic_url_fetch()`'s JSON-LD probe + headless-Chromium fallback (Options
  A/B) and an `Enrichment Attempts` retry ceiling (Option D). Only Option C (a paid scrape API,
  deferred — only worth it if headless rendering proves too heavy for the nightly runner) remains
  open. Full history: `docs/refinement-plans/sourcing/career-site-enrichment-fallback.md`.

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
