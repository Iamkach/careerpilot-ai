# TODO — standalone fixes and reminders

This file is scoped to **small, standalone** code/development-blocking items only — quick fixes
and reminders for the next execution. It is not an index of open roadmap stories: every feature's
problem statement, design decisions, and open residual gaps lives in its own `spec/<feature>/`
folder — see `spec/INDEX.md` for the current list. See `docs/CHANGELOG.md` for what's already
landed.

Outstanding runtime/ops issues (GitHub Actions secrets, CI gate, integrations — nothing that
touches this repo's code) live in `docs/RUNTIME_NOTES.md` instead.

## Small, standalone fixes

- **Step 11 fresh-fork verification (2026-07-30).** Step 11 (`--init` wizard + Notion
  provisioning + profile.json de-personalization) is fully implemented and on `main`: it merged
  via PR #19 into `feature/step-10-auto-apply`, and that whole branch — Step 10 and Step 11
  together — merged to `main` via PR #20 on 2026-07-30. The one thing never actually run: a
  fresh-fork dry run confirming `--init` end-to-end (Notion provisioning + profile wizard + `gh`
  secret sync) works for someone who isn't the original owner.

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

- **`scripts/dev_check.py` doesn't exist (found 2026-08-20).** `CLAUDE.md`'s "Definition of Done"
  section mandates running it every session as the hygiene gate (git status/branch checks, line
  endings, then `pytest`), but the file was never created — every session has been trusting a doc
  that describes a script that isn't there. Either write it (git status/branch-relationship/
  line-ending checks + `pytest -v`, matching what `CLAUDE.md` already describes) or correct
  `CLAUDE.md` to stop claiming it exists. Substituted manually this session:
  `git status` + full `pytest -v`.

- **Two local-environment-polluted test failures, not code bugs (found 2026-08-19/20).**
  `tests/test_autoapply_answer_quality.py::test_preset_bank_never_fabricates_a_history_answer`
  fails because a real `config/application_profile.json` (git-ignored, from a prior
  `--setup-profile` run) overlays `"ever interviewed": "No"` onto `COMMON_QUESTION_PRESETS` at
  import time, leaking into a test that assumes the *default* bank ships that preset blank.
  `tests/test_sources_robustness.py::test_discover_tokens_stops_probing_at_budget` fails because
  `discover_tokens()` seeds in a real `"Notion Seed Co"` from `get_target_companies_from_notion()`
  that the test never mocked out, throwing off its exact probe-budget assertion. Both reproduce on
  a clean `pytest -v` in this checkout and are unrelated to any in-flight code change — either
  isolate `config/settings.py`'s profile overlay and the Notion seed call in these two tests, or
  accept this as expected drift from running against a real local `.env`/profile.
