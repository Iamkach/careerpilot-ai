# Changelog — refinement-plans / backlog work landed

Consolidated record of work completed from the `refinement-plans/` → `backlog/` roadmap
(`docs/refinement-plans/README.md`, Steps 0–7). Written from a code audit, not from backlog
checkboxes — several stories claimed more progress than the code showed. Superseded backlog
stories and refinement plans are deleted once their scope is fully landed; see
`docs/TODO.md` for what's still open.

## Stage 6 crash fix (quick-fix 1)

`stage6_negotiate.py` used `job` before it was assigned, so `python run.py --stage 6` raised
`UnboundLocalError` on every invocation. Reordered so `job` is fetched before first use.

## Step 1 — Sourcing spike

Two confirmed dead ends replaced:
- `bebity~indeed-scraper` (404, deprecated) → `misceres~indeed-scraper`.
- `bebity~linkedin-jobs-scraper` (paid $29.99/mo rental, payload fields didn't even match the
  actor) → `valig~linkedin-jobs-scraper` (pay-per-event, no cookie, returns
  `recruiterName`/`applicant_count`/`salary_range` as a side effect).

`LINKEDIN_ACTOR`/`INDEED_ACTOR` and their payload builders now live in `scripts/sources.py`.
Net effect: cheaper, unblocked, and the actor/payload mismatch that made Stage 1's real
volume unmeasurable is gone. Production run on 2026-07-13 added 151 new jobs.

## Step 2 — Notion schema migration + writer error-surfacing

`_notion_write_job()` (`scripts/utils.py`):
- Accepts a caller-supplied `status` instead of hardcoding `"Scraped"`.
- `if job.get("ats_score") is not None:` — no longer silently drops a genuine score of `0`.
- Writes `Sponsorship`, `Scoring Attempts`, `Posted Date`, `Source`, `Applicant Count`,
  `Salary Range` when present.
- Bare `except: return None` replaced with one that logs the real Notion exception; a
  `Sponsorship`-write failure specifically retries once without that property rather than
  failing the whole page.

`_notion_promote_to_scraped()` takes a `status` param and writes `Sponsorship`.
`_page_to_job()` round-trips `sponsorship` and `scoring_attempts`.

**Known gap carried to `docs/TODO.md`:** `_notion_update()` (`utils.py:432`) still has a bare
`except: pass` with no logging.

## Step 3 — Dedup self-match fix

`ingest_interested_from_notion()` was retiring every "Interested" row with a URL straight to
`Scraped` with no score and no cached JD, because it looked itself up by URL and matched its
own page. Fixed:
- `db_find_job_by_url()` gained `exclude_page_id`.
- `ingest_interested_from_notion()` passes its own page id.
- The `existing_urls` dedup snapshot in `run()` excludes unsettled statuses (`Interested`).
- `scrape_job_urls()` now distinguishes a failed enrichment (`None`) from a real empty result
  (`{}`), instead of returning `{}` for both.

**Known gap carried to `docs/TODO.md`:** the two manual end-to-end verification checks from
the original story were never run.

## Step 4 — Filtering pure functions

- `is_skipped_company()` rewritten to token-boundary matching (`_tokens`/`_strip_suffix`/
  `_subseq` in `scripts/utils.py`) — fixes false positives like `"ust"` matching
  `"customer.io"`, `"igate"` matching `"navigate"`.
- `_jd_excerpt(desc, head=1200, tail=800)` replaces the old `[:1500]` truncation so the
  AI/regex sponsorship check actually sees the EEO/work-authorization block that usually sits
  at the bottom of a JD.

## Step 5 — Scoring reliability + AI company_type classification

`score_jobs_batch()` (`scripts/stage1_scrape.py`) no longer fabricates `score=50,
sponsorship="unknown"` on failure — neither on a whole-batch exception nor on a URL missing
from a successful response. Both cases now return `scored=False`, and callers write the job
to Notion as `Status="Retry"` with an empty ATS score instead.

- `rescore_retry_jobs()` runs at the top of every stage 1 `run()` (right after
  `ingest_interested_from_notion()`), re-scoring every `Retry` row from its already-cached JD
  body — no repeat Apify call — and incrementing `Scoring Attempts` each pass. Past
  `MAX_SCORING_ATTEMPTS` (`config/settings.py`), a job is promoted to `Scraped` with an empty
  score rather than retried forever.
- The scoring prompt now also classifies `company_type` (`product` / `staffing_or_consulting`
  / `agency` / `unknown`) in the same call — no second round-trip. A job whose type is in
  `SKIP_COMPANY_TYPES` (`{"staffing_or_consulting"}` by default) is dropped and logged
  `[STAFFING/AI]`, but only when `scored` is `True` — an unscored/failed batch is never
  dropped on `company_type == "unknown"`.
- `ai_chat()`/`ai_chat_blocks()` (`scripts/utils.py`) gained retry-with-backoff (3 attempts,
  2s/8s) on transient errors (timeouts, 429/5xx) and typed exceptions: `AIChatError` on
  retry exhaustion, `AIUsageCapError` raised immediately (no blind retry) on a detected
  Claude Code subscription usage-cap error.
- `ingest_interested_from_notion()` inherits the same `scored` gating — an unscored
  hand-picked job stays `Retry` (already enriched/JD-cached) instead of promoting to
  `Scraped`.
- `run.py --setup` prints the current `Retry`-queue count.
- Requires one manual Notion step: add `Retry` as a `Status` select option (the API can't
  create select options on a write that references them).

**Not in scope:** the `AI_ROUTING`/tiering design and any `workflow.py` changes from the
original plan — both are superseded by the shipped `FAST_PROVIDER`/`QUALITY_PROVIDER` +
nightly-workflow approach (see below). `workflow.py` itself is deleted; not resurrected.

## Step 6 — Multi-source sourcing (Greenhouse/Lever/Ashby + cross-source dedup + freshness)

New `scripts/sources.py`: `KEYWORD_SOURCES` (LinkedIn, Indeed via Apify) and `BOARD_SOURCES`
(Greenhouse, Lever, Ashby — free, keyless JSON APIs) behind one registry, controlled by
`ENABLED_SOURCES` in `config/settings.py`. `TARGET_COMPANIES` finally has a consumer.

- `job_fingerprint()` / `collapse_by_fingerprint()` dedup the same job posted to multiple
  sources, keeping the highest-priority copy (`SOURCE_PRIORITY` — ATS boards beat
  LinkedIn/Indeed since they carry the full JD, real date, and direct-apply URL).
- Freshness: `_is_fresh()` against `MAX_JOB_AGE_DAYS` (14) / `DROP_UNDATED_JOBS` (False),
  checked immediately after the seen-URL check in `_pre_filter()`.
- `discover_tokens()` probes each seed company's Greenhouse/Lever/Ashby board and caches hits
  and misses to `config/ats_tokens.json`; Greenhouse responses are verified against the
  company name, Lever/Ashby auto-accepts are logged loudly for manual review.
- `run()` restructured to global gather → collapse → filter → score (a duplicate can span
  roles and sources, so per-role processing couldn't see it before).

## Step 8 — Runtime `--ai-mode` flag + dynamic metered provider

`run.py --ai-mode {metered,hybrid,subscription}` sets `FAST_PROVIDER`/`QUALITY_PROVIDER` env
vars for a single invocation, before any `config.settings` import — the interactive equivalent
of hand-setting those env vars, without editing `config/settings.py` or `.env`. Omitting the
flag leaves today's behavior (including the nightly workflow's own env vars) untouched.

Expanded beyond the original spec: the metered tier is no longer hardwired to `claude`.
`--metered-provider {claude,codex,gemini,openrouter}` (default `claude`) picks which metered
backend fills `metered`'s both tiers / `hybrid`'s fast tier (`subscription` ignores it —
always `claude_code`/`claude_code`). This required a fourth metered backend: `openrouter`
(`scripts/utils.py` `_chat_openrouter`) — OpenRouter's OpenAI-compatible endpoint, fronting
many vendors' models (Anthropic, OpenAI, Google, Meta, ...) behind one `OPENROUTER_API_KEY`,
wired into `_BACKENDS`/`_DEFAULTS`/`MODEL_OVERRIDES` the same way as the existing
`claude`/`gemini`/`codex` providers — no changes needed to `_active_provider()`'s resolution
logic.

## Not in any refinement plan, but shipped

- **Typed `NotionReadError` — clean read-failure handling across every CLI path (2026-07-21).**
  Closes the `docs/TODO.md` "Open for review" item where only `--ingest` turned a failed Notion
  read into a clean message + non-zero exit, while `--retry-only`, `--evaluate`, and
  `--stage 2/3/4` (via the previously-unguarded `db_get_jobs()` / `db_get_ready_to_apply()`)
  dumped a raw traceback. `scripts/utils._query_db()` — the single funnel every reader uses —
  now raises `NotionReadError` (a `RuntimeError` subclass) on failure; `run.py`'s `main()`
  catches it once around the whole dispatch. Typed on purpose so the unrelated `RuntimeError`s
  from Apify / provider setup / stage 5 are **not** mislabeled as a tracker read failure. Tests:
  `tests/test_run_notion_read_failure.py` + contract cases in
  `tests/test_utils_read_failure_contract.py`.
- **`_prop_number_opt()` — absent-vs-real-`0` score reads (2026-07-21).** Closes the other
  `docs/TODO.md` "Open for review" item: `_prop_number()` returned `0` for both an empty
  property and a genuine `0`, colliding with stage 1's "never fabricate a score" contract. A new
  nullable reader `_prop_number_opt()` returns `None` for absent / the real number otherwise, and
  is used **only** for `ATS Match Score` in `_page_to_job()` / `db_get_all_jobs()`; `_prop_number`
  still backs the counters (`Scoring Attempts`/`Enrichment Attempts`/`Applicant Count`/`Apply
  Attempts`) where `0` is the right default. Score consumers in `stage4_digest.py` /
  `stage3_outreach.py` hardened to `… or 0` so an unscored `None` can't `int(None)`-crash the
  digest. No behavior change in practice (`MIN_ATS_SCORE=30` already drops any 0-score job before
  write); future-proofs the read path. Tests: new cases in `tests/test_utils.py`.
- Stage 2 sponsorship gate (`RESTRICTED_SPONSORSHIP_COMPANIES`, `_sponsorship_gate()` in
  `scripts/stage2_tailor.py`) — holds jobs at companies known to sponsor only existing
  employees, moving them to `Human Review` instead of tailoring a resume.
- `MIN_ATS_SCORE` filter in Stage 1 to skip low-scoring jobs before they hit Notion.
- `.github/workflows/nightly-pipeline.yml` — scheduled off-hours run with
  `FAST_PROVIDER=claude` / `QUALITY_PROVIDER=claude_code` hybrid routing. This supersedes the
  `AI_ROUTING`/tiering design in `refinement-plans/reliability/hybrid-agentic-migration-plan.md`
  §1 and `workflow.py` §4 — `workflow.py` itself was deleted (`cc7b6d8`), making `run.py` the
  sole entry point, and the default provider switched to metered `claude` for interactive runs
  (`ab97add`). Don't resurrect the `AI_ROUTING` design; this is the shipped replacement.

## Step 9 — Evals / testing strategy

The repo had zero automated tests and no `on: pull_request`/`on: push` CI trigger before this
story — `.github/workflows/nightly-pipeline.yml` is the live production cron job, not a test
gate. Landed in six phases (0-5), all independently shippable:

- **Phase 0** — `requirements-dev.txt` (`pytest`, `pytest-mock`), `tests/conftest.py` (a fake
  `ai_chat`/`ai_chat_blocks` monkeypatch and an in-memory fake Notion layer over `scripts/utils.py`'s
  `db_*` functions), and `.github/workflows/tests.yml` on `pull_request`/`push`, separate from
  `nightly-pipeline.yml`.
- **Phase 1** — pure-function unit tests: `sources.py` (`job_fingerprint`,
  `collapse_by_fingerprint`, `title_matches_targets`, `_is_fresh`, `_to_iso_date`,
  `_parse_salary`), `utils.py` (`matches_company_list`, `parse_json_response`),
  `stage2_tailor.py`'s `_sponsorship_gate`, `stage6_negotiate.py`'s `get_company_type`, and
  characterization tests for the stage 5/6 markdown→HTML converters' missing `<ul>` wrapping.
- **Phase 2** — docx golden-file tests for `render_docx.py`'s `extract_docx_text` /
  `apply_docx_edits`, including characterization tests for the run-collapsing formatting-loss and
  same-paragraph double-edit clobber edge cases.
- **Phase 3a** — a one-time real-call recording pass via Claude Code (free under the
  subscription), run manually against `score_jobs_batch`/`_score_jobs_chunk`,
  `tailor_resumes_batch`/`_tailor_resume_single`, and stage 3's outreach draft call at batch
  sizes bracketing the chunk boundary (1, 20, 21, 50, 100+) plus empty/garbled-description and
  huge-keyword-hint inputs. Saved verbatim under `tests/fixtures/recorded_ai_responses/`; never
  re-run by CI.
- **Phase 3b** — mocked AI-flow contract tests seeded from the Phase 3a recordings (not
  hand-typed), including a permanent regression test for the 2026-07-16 incident where
  `score_jobs_batch` sent an entire 100+-job scrape in one AI call, truncating the JSON reply
  and blanking every job's score — now split into `_SCORE_CHUNK_SIZE`-sized chunks, and a test
  asserts one chunk's failure only blanks that chunk's jobs, not the whole batch. Also documents
  (without fixing) the unclamped-ATS-score gap and the cold-email fallback's ad-hoc JSON
  stripping.
- **Phase 4** — `tests.yml` runs the full mocked suite (129 tests, ~1.5s) on every PR/push, no
  `ANTHROPIC_API_KEY`/`NOTION_API_KEY`/`APIFY_API_TOKEN` or Claude Code login needed anywhere.
- **Phase 5** — `scripts/run_evals.py`, a standalone opt-in script (never invoked by `run.py`,
  `--evaluate`, or any CI workflow) that hits the real Anthropic API against a 10-entry
  hand-labeled dataset (`tests/eval_data/jobs.json`) covering strong/medium/weak resume-match
  quality, a staffing-agency posting, explicit and ambiguous sponsorship language, and
  empty/garbled JDs (excluded from aggregates, observational only). Reports score-hit-rate
  (predicted score vs. human-assigned expected range), sponsorship/company-type classification
  accuracy, fuzzy keyword recall against a labeled missing-keywords set, and (with `--tailor`)
  stage 2's before→after ATS delta. `--comp-check` prints one sample stage 6 negotiation brief
  for manual staleness review — there's no fixed oracle for comp-benchmark accuracy, since
  `generate_negotiation_brief`'s prompt draws on the model's own training knowledge despite the
  module docstring's "Claude + web search" claim (no actual search tool is called). Intended to
  be run manually around prompt or `QUALITY_MODEL`/`AI_MODEL_OVERRIDE` changes, not on a
  schedule.

Full spec (retired): `docs/backlog/step-9-evals-testing.md` and
`docs/refinement-plans/testing/evals-strategy.md`.

## Step 12 — Notion-managed restricted-sponsorship company list

Replaced the plan to hold a specific posting via a per-job Notion Notes marker with a
different fix for the same underlying problem (a hardcoded, committed
`RESTRICTED_SPONSORSHIP_COMPANIES` list can't be edited without a redeploy, and silently
blocks a company forever even after its policy changes): the restricted-company list itself
moved into its own Notion database, parallel to the Jobs Tracker and Scratch Pad
(`NOTION_RESTRICTED_COMPANIES_PAGE_ID`) — editable visually, no code change needed, and works
identically from a future GitHub Actions run (unlike a git-ignored local file).
`get_restricted_sponsorship_companies()` (`scripts/utils.py`) merges the Notion list with the
hardcoded list as a fallback/escape hatch. Enforced at **stage 1** as a silent drop at scrape
time, like `SKIP_COMPANIES` (`is_restricted_sponsorship_company()`, new
`restricted-sponsorship` drop counter); stage 2's existing `_sponsorship_gate()` keeps
checking the same merged list as defense-in-depth, for a job that reached `Reviewed` before
its company was added.

Full spec (retired): `docs/backlog/step-12-sponsorship-restriction-marker.md`.

## Step 11 — Forkable setup (Phases 1 + 2)

`scripts/provision_notion.py` + `run.py --init` provision the "Careerpilot-ai" page + all three
databases and env-source `NOTION_DB_ID` (hardcoded literal removed); `--setup` validates the live
schema. **Phase 2 (identity):** owner identity de-hardcoded in `config/settings.py`
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
`profile.json` from its secret.

## Step 10 — Auto-Apply subsystem, Phases 1–2 (Stage 7)

`scripts/autoapply.py` (Layer 1, no browser) + `scripts/autoapply_browser.py` (Layer 2,
Playwright), wired in as `run.py --stage 7` / `--stage 7 --fill`. **Never submits** — the human
clicks Submit and sets `Applied` by hand; `WRITABLE_STATUSES` excludes `Applied` on purpose, and
there is no submit code path in `autoapply_browser.py` at all, guarded by
`tests/test_autoapply_notion.py`. `detect_apply_channel()` routes by URL domain; Greenhouse gets a
real field schema via its public `?questions=true` endpoint, everything else falls back to
`GENERIC_QUESTIONS` with `schema_known=False`. `_resolve_field()` resolves each field through an
ordered chain (file upload → name map → label rules → `COMMON_QUESTION_PRESETS` → free text →
`review_required`); work authorization, sponsorship, and salary come only from
`APPLICATION_PROFILE` or block — never guessed. `AUTOAPPLY_DRAFT_ESSAYS` drafts free-text answers
from the cached JD + tailored resume but leaves `status`/`value` untouched, so a draft is never
auto-typed. `run.py --setup-profile` (`scripts/autoapply_profile.py`) writes answers to a
git-ignored `config/application_profile.json`. `FILLABLE_CHANNELS = {greenhouse, lever}` — LinkedIn
and Indeed are excluded by rule (ToS/detection risk), not configuration.

A later fix (commit `0e22a6c`, 2026-07-30) closed four defects found while planning real
Greenhouse jobs, cutting projected blockers on a 12-job sample from 44 to 19: identity was
resolving to the literal `"Your"`/`"Name"` and reading as answered (now derived from `YOUR_NAME`,
and the placeholder correctly blocks); `COMMON_QUESTION_PRESETS` matching was raw substring and
matched none of three real "years of experience" phrasings (now an ordered word-subsequence
match, `_label_matches_pattern()`); free-text essays were never actually drafted despite being
documented as AI-assisted; and `_LABEL_RULES` checked work-authorization before sponsorship, so a
label containing both substrings resolved from the wrong key — silently wrong for anyone whose two
flags differ, now reordered.

**Phase 3 (deliberate submit) deferred by choice**, pending real-world use of the fill path. Full
spec, open gaps, and Phase 3 design: `docs/backlog/step-10-auto-apply-subsystem.md`.

## Step 15 — Application pre-fill browser extension (Stage 7 Layer 3)

Queued 2026-07-30, not started. An MV3 extension + localhost bridge that pre-fills whatever
application form is open in the user's own authenticated browser: the content script scrapes the
live DOM into the exact schema shape `build_application_plan()` already consumes, so Ashby,
Workday, and arbitrary custom career sites become one code path with no per-ATS schema or selector
work, and the human is already past auth/captcha since it's their real session. Complements rather
than replaces the Stage 7 Layer 2 Playwright path (which stays `{greenhouse, lever}`-only): the
extension is interactive-only and does nothing for an unattended run.

Folded from `docs/refinement-plans/auto-apply/browser-extension-prefill.md` on a scoping
correction to `docs/refinement-plans/auto-apply/sourcing-bottleneck-analysis.md`'s original
sizing, which counted rows the pipeline can auto-route to a fillable URL — an extension routes
nothing, so the real population is every application opened by hand, including custom career
sites reached through a LinkedIn posting. `docs/refinement-plans/auto-apply/ashby-workday-custom-fill.md`
(a per-ATS Playwright-adapter alternative to the same bottleneck) was superseded and deleted in
the same change; its one still-live idea (Ashby in `FILLABLE_CHANNELS`, for unattended runs only)
is harvested into the Step 15 story's "Considered and dropped."

Full spec: `docs/backlog/step-15-application-prefill-extension.md`.

Full spec: `docs/backlog/step-11-forkable-setup.md`.
