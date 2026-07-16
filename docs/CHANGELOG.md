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
