# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Job Search Pipeline** — Automated job search using Claude API (no N8N, no VPS required).

Scrapes jobs from multiple sources (LinkedIn + Indeed via Apify, Greenhouse/Lever/Ashby directly), tailors resumes per job, drafts cold/warm outreach emails, generates interview prep guides, and negotiates offers. Progress is tracked in **Notion** (the single source of truth — the job tracker database).

### Key Dependencies
- `anthropic` — Claude metered API (default provider `AI_PROVIDER="claude"`)
- `notion-client` — **Primary data store** (the job tracker database)
- `claude-agent-sdk` — optional: Claude Code subscription path (`AI_PROVIDER="claude_code"`)
- `google-generativeai` / `openai` — Alternative AI providers
- `requests` — HTTP client for Apify

## Architecture

### Single entry point

**`run.py`** — Deterministic stage runner. Python decides the order; AI is called as a subroutine (`ai_chat`) for scoring and tailoring only. Uses `--stage` / `--evaluate` / `--ingest` flags. Honors `AI_PROVIDER`.

> Note: `run.py` is *not* agentic. Under the `claude_code` provider it reaches the subscription through the Agent SDK, but `_sdk_text()` runs with `allowed_tools=[]` and `max_turns=1` — a one-shot prompt→text call. The SDK is a transport, not a loop. The default provider is `claude` (metered API), which doesn't touch the SDK at all.

`workflow.py` — an earlier Claude-agentic orchestrator (Claude decided which stage to run via an in-process MCP server whose tools were thin wrappers over the same stage `run()` functions) — was removed. It always drove its own reasoning loop through the Claude Code Agent SDK regardless of `AI_PROVIDER`, which meant a subscription session-window limit on runs of any length; `run.py` has no such constraint and reads/writes the exact same stage scripts and Notion schema.

### Pipeline stages

| Stage | File | Purpose |
|-------|------|---------|
| 1 | `scripts/stage1_scrape.py` | Scrape every source in `ENABLED_SOURCES` via `scripts/sources.py` (+ ingest Notion "Interested" jobs), score against resume (ATS 0–100), save to Notion as "Scraped" — or "Reviewed" for confident jobs (`Sponsorship = yes` and score ≥ `AUTO_REVIEW_MIN_SCORE`) |
| 2 | `scripts/stage2_tailor.py` | Fetch "Reviewed" jobs, apply targeted ATS keyword edits in-place to the base `.docx`, save to `output/resumes/` |
| 3 | `scripts/stage3_outreach.py` | Draft cold/warm outreach emails, save to `output/outreach/` |
| 4 | `scripts/stage4_digest.py` | Generate morning HTML digest of ready-to-apply jobs |
| 5 | `scripts/stage5_interview_prep.py` | Generate HTML interview prep guide |
| 6 | `scripts/stage6_negotiate.py` | Research salary benchmarks and draft HTML negotiation brief |

### Data flow

```
Notion jobs database  ←→  all stages (primary, single source of truth)
       ↑
scripts/sources.py: Apify (LinkedIn, Indeed) + Greenhouse/Lever/Ashby (direct JSON APIs)  →  stage 1
```

### Multi-source sourcing (`scripts/sources.py`)

Stage 1 gathers from a registry rather than hardcoding two scrapers:
- `KEYWORD_SOURCES = {"linkedin": ..., "indeed": ...}` — Apify actors, searched per `TARGET_ROLES`
- `BOARD_SOURCES = {"greenhouse": ..., "lever": ..., "ashby": ...}` — free, keyless JSON APIs,
  crawled per company (seeded from `TARGET_COMPANIES` ∪ every company already in Notion), filtered
  to `TARGET_ROLES` matches by `title_matches_targets()`
- `config/settings.py`'s `ENABLED_SOURCES` controls which registry entries actually run

Every source function returns the same dict shape (`url, title, company, location, description,
source, posted_date, applicant_count, salary_range`). `run()` does a **global gather → collapse →
filter → score**, in that order:
1. Gather raw listings from every enabled source across all roles/companies in one pass (a
   duplicate can span both roles and sources, so per-role processing can't see it).
2. `collapse_by_fingerprint()` merges same-company-same-title duplicates across sources —
   `job_fingerprint(company, title)` normalizes both fields (strips legal suffixes/parentheticals,
   keeps seniority tokens) — keeping the copy from the highest-priority source per
   `SOURCE_PRIORITY` (ATS boards win over LinkedIn/Indeed: fuller JD, real date, direct-apply URL).
3. `_pre_filter()` in `stage1_scrape.py` runs freshness (`_is_fresh()` vs `MAX_JOB_AGE_DAYS`/
   `DROP_UNDATED_JOBS`) immediately after the seen-URL check, then the existing company/title/
   location/sponsorship/duplicate checks (now also checking the fingerprint, not just the URL).
4. Survivors are scored in one batched AI call as before.

`discover_tokens()` probes each seed company's Greenhouse/Lever/Ashby board and caches hits **and**
misses to `config/ats_tokens.json` (re-probes an all-null entry only after ~30 days). Greenhouse
responses are verifiable (`company_name` field) and rejected on a mismatch; Lever/Ashby have no
such field, so an auto-accepted token is logged loudly for the user to pin or veto by hand.

**Backup plan if Apify sourcing (`valig`/`misceres`) stops being satisfactory:** adopt
`python-jobspy` as a `KEYWORD_SOURCES` entry — see the "Backup plan" section in
`docs/backlog/step-6-multi-source-phase1.md` for the concrete integration steps and the two known
caveats (LinkedIn rate-limiting without a proxy; mixed library maintenance signal). Not adopted
preemptively — only worth doing once the Apify pair is actually observed degrading.

Status pipeline: `Interested (manual intake) → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received`

Off-pipeline states (`Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review`) exist as
select options and are set **by hand** — no stage writes them, with one deliberate exception:
stage 2's sponsorship gate (see below) moves a `Reviewed` job to `Human Review` on its own. Since
`db_get_jobs()` filters on an exact status, a row parked in one of them is simply never picked up.
Dedup is the exception: it spans every status, so a `Disregard`d job is not re-scraped.

### Two-step daily flow

The pipeline has a human review gate between scraping and tailoring — but Stage 1 now
**auto-promotes the confident cases past it**. Silence on sponsorship is not treated as a
red flag (most companies willing to sponsor simply don't say so in the JD): a scored job
whose sponsorship isn't explicitly ruled out (`Sponsorship = yes` or silent/`unknown`) and
scores at/above `AUTO_REVIEW_MIN_SCORE` (`config/settings.py`, default 35) lands directly in
`Reviewed`, skipping the manual step; only an explicit `Sponsorship = no` or a lower score
still lands in `Scraped` for a human second-eye pass. The gate decision lives in one helper,
`_auto_review_status()` in `scripts/stage1_scrape.py`, applied at all three places a job
would otherwise land in `Scraped` (fresh scrape, "Interested" intake, Retry recovery).
It runs **after** the drop gates (`EXCLUDE_NO_SPONSORSHIP == "no"`, `SKIP_COMPANY_TYPES`,
`MIN_ATS_SCORE`), so it only ever sees jobs that already survived them.

1. **Scrape & review** — `python run.py` runs stages 1 + 4: scrape LinkedIn, score, and emit a review digest of "Scraped" jobs (the auto-`Reviewed` jobs skip this digest by design). **Stop here.**
2. **Review in Notion** — open the tracker and set `Status = Reviewed` on any remaining `Scraped` jobs worth applying to.
3. **Evaluate** — `python run.py --evaluate` reads the "Reviewed" jobs straight from Notion (both auto-promoted and hand-marked), then runs stage 2 (tailor) → stage 3 (outreach drafts, non-interactive) → stage 4 (ready digest).

### Manual job intake ("Interested")

Jobs the user finds by hand (e.g. LinkedIn connections/suggestions) are added **in Notion**: create a row with Job Title, Company, Job URL and `Status = Interested`. On the next Stage 1 run (or `python run.py --ingest`), `ingest_interested_from_notion()` enriches each via Apify, scores it, and promotes that same Notion page to "Scraped" — or straight to "Reviewed" via the same `_auto_review_status()` gate (`Sponsorship = yes` and score ≥ `AUTO_REVIEW_MIN_SCORE`) — caching the JD in the page body, after which it behaves like any scraped job. Hand-picked jobs bypass the `SKIP_COMPANIES` / US-location / sponsorship filters.

### Scratch-note intake (fast mobile drop)

A lower-friction alternative to filling in a full Notion Jobs-Tracker row per link: create one small Notion **database** (a "list" view works well) — e.g. titled "Job Link Scratch Pad" — where each row's title is one job URL and nothing else needs filling in. Share it with the same integration used for `NOTION_API_KEY`, and set its database id as `NOTION_SCRATCH_PAGE_ID` (optional; the feature no-ops if unset). From mobile, adding a link is just "+ New" → paste the URL as the title. On the next Stage 1 run (or `python run.py --ingest`), `ingest_from_scratch_note()` runs first: it reads every row (finding the URL by the row's title property, whatever that column happens to be named — extra columns in the database are ignored), creates a minimal `Status = Interested` row (Job Title = "Pending intake") for every URL not already tracked anywhere in the Jobs DB, then archives that scratch-database row so it isn't reprocessed (a row whose row-creation fails is left un-archived and retried next run; a row whose URL is already tracked under any status is archived without creating a duplicate). `ingest_interested_from_notion()` then picks up those freshly-created rows in the same run exactly as if they'd been entered by hand.

### Shared utilities (`scripts/utils.py`)

- `ai_chat(prompt, system, max_tokens, quality)` — provider-agnostic chat; `claude_chat` is an alias
- `ai_chat_blocks(blocks, ...)` — Claude-only structured content blocks with `cache_control`
- `db_find_job_by_url()` — one-off URL lookup. Returns the page id, or `None` for a genuine miss; **raises `RuntimeError` on a failed read** rather than returning `None`, since `None` means "no such job" and callers act on it by creating a row
- `db_add_job()`, `db_update_status()`, `db_get_jobs()`, `db_get_all_jobs()`, `db_get_ready_to_apply()`, `db_get_job_by_company()`, `db_get_job_description()` — Notion-backed CRUD (`page_id`/`id` is the Notion page id; the JD is cached in the page body via paragraph blocks)
- `db_get_all_jobs()` — one unfiltered paginated read of every row (`page_id, title, company, location, url, status, ats_score`); backs Stage 1's in-memory dedup (URL set + fingerprint set). **Raises `RuntimeError` on a failed read** — Stage 1 aborts the scrape rather than treating a failed read as an empty DB (which would mass-duplicate the tracker)
- `db_add_job_linked(job, notion_page_id)` — promote an existing manually-added Notion page ("Interested" intake) to "Scraped" in place (no duplicate page); caches the JD in its body
- `get_notion_jobs_by_status(status)` — read Notion rows by status (paginated, via `_query_db()` like every other reader). **Raises `RuntimeError` on a failed read**, same contract as `db_get_all_jobs()` — a failed read must never be reported as "no rows with this status", since callers act on emptiness by creating rows. `sync_notion_to_supabase()` is now a no-op kept for compatibility (Notion is the store)
- `get_scratch_note_entries()` / `archive_scratch_note_entry(page_id)` / `db_add_interested_url(url)` — the scratch-note read/archive/create helpers backing `ingest_from_scratch_note()` above (see "Scratch-note intake")
- `load_resume()`, `ensure_dirs()`, `today()`, `parse_json_response()` — misc helpers

**Configuration:** `config/settings.py` — all API keys, user profile, target roles, AI model settings, output paths.

## Common Commands

```bash
python run.py                                                    # Scrape + review digest (stages 1, 4) — STOP for review
python run.py --ingest                                          # Promote scratch-note URL drops, then ingest Notion "Interested" jobs → Scraped
python run.py --evaluate                                        # Sync "Reviewed" from Notion, then tailor + outreach + digest
python run.py --setup                                            # Verify config
python run.py --stage 1                                          # Scrape only (also ingests "Interested")
python run.py --stage 2 --min-score 65
python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
python run.py --stage 4 --send
python run.py --stage 5 --company "Meta" --role "Senior PM"
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000
python run.py --ai-mode {metered,hybrid,subscription} --metered-provider {claude,codex,gemini,openrouter}  # Per-run override
```

## Key Design Patterns

1. **Notion-first** — Notion is the single source of truth. All stages read/write the Notion jobs database via the `db_*` helpers; `NOTION_API_KEY` + DB sharing are required.
2. **Two-model setup** — `AI_MODEL_OVERRIDE` (fast/cheap, e.g. Haiku) for scraping/outreach; `QUALITY_MODEL` (e.g. Sonnet) for tailoring/interview prep/negotiation. Both set in `config/settings.py`.
3. **Idempotent stages** — Duplicates skipped by exact Job URL match **and** by company+title fingerprint (`job_fingerprint()` in `scripts/sources.py`, catching the same req posted to multiple sources). Stage 1 reads every existing row once via `db_get_all_jobs()` and dedups against that in-memory URL/fingerprint set, rather than querying Notion per listing. `db_find_job_by_url()` remains for one-off lookups (e.g. "Interested" intake).

   Only `Interested` is excluded from that snapshot, and only because `ingest_interested_from_notion()` promotes such a row **in place** — counting it would make it dedup against itself. Every other status, `Retry` included, must stay in the snapshot: the fresh-scrape path calls `db_add_job()`, which creates a *brand-new* page, so a job left at `Retry` by `rescore_retry_jobs()`'s still-retrying branch would otherwise get a second Notion page on the very next run.
4. **Manual review gates** — A "Reviewed" gate sits between scraping and tailoring (user marks jobs in Notion before `--evaluate`), **except** for confident jobs Stage 1 auto-promotes straight to `Reviewed` (`Sponsorship = yes` and score ≥ `AUTO_REVIEW_MIN_SCORE`; see `_auto_review_status()` and "Two-step daily flow"). Outreach drafts are saved but not auto-sent; user reviews `output/outreach/` files first.
5. **Prompt caching** — `utils.py` `ai_chat_blocks()` caches structured blocks, but only on the metered `"claude"` provider; every other provider joins the blocks into plain text. On the `claude_code` path the CLI manages its own caching.
6. **Adding a provider** — Add a `_chat_<name>` function to `_BACKENDS` dict in `scripts/utils.py`. No other changes needed.

## Stage 1 Filters

Settings in `config/settings.py` control what gets saved:
- `SKIP_COMPANIES` — word-boundary denylist for consulting/staffing firms; grows over time
- `EXCLUDE_NO_SPONSORSHIP = True` — skips jobs that explicitly deny visa sponsorship
- `ENABLED_SOURCES` — which `scripts/sources.py` registry entries run (`linkedin`, `indeed`,
  `greenhouse`, `lever`, `ashby`)
- `MAX_JOB_AGE_DAYS` / `DROP_UNDATED_JOBS` — freshness window applied to `posted_date`; a source
  that doesn't expose a date is kept by default unless `DROP_UNDATED_JOBS = True`
- `AUTO_REVIEW_MIN_SCORE` (default 35) — not a filter: a saved job with `Sponsorship = yes`
  scoring at/above this skips the manual `Scraped → Reviewed` gate and lands in `Reviewed`
  directly (`_auto_review_status()`). Applied after the drop filters above, at all three
  save paths (fresh scrape, "Interested" intake, Retry recovery)

## Stage 2 Sponsorship Gate

`RESTRICTED_SPONSORSHIP_COMPANIES` in `config/settings.py` is a manually-curated list of
product companies known (from your own research/contacts) to sponsor only **existing**
employees, not new external hires — even when the JD reads as sponsorship-friendly or says
nothing. Unlike `SKIP_COMPANIES`, these are **not** excluded in stage 1 — they're scraped,
scored, and tracked normally. Instead, stage 2 (`_sponsorship_gate()`) holds back any
`Reviewed` job whose company matches this list: it moves that job's Notion Status to
`Human Review` and writes a guidance note, without tailoring a resume. To release a held
job, confirm sponsorship for a new hire yourself, add `SPONSORSHIP_CONFIRMED_MARKER`
(default: `"sponsorship confirmed"`) to that job's Notion **Notes** field, then move its
Status back to `Reviewed` by hand — stage 2 checks for the marker before re-gating it.

## Switching AI Provider

Set `AI_PROVIDER` in `config/settings.py`:

| `AI_PROVIDER` | Key setting | Default model |
|---|---|---|
| `"claude"` (default) | `ANTHROPIC_API_KEY` | `claude-opus-4-6` |
| `"claude_code"` | Claude Code subscription (`claude /login`) | `sonnet` |
| `"gemini"` | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| `"codex"` | `OPENAI_API_KEY` | `gpt-4o` |
| `"openrouter"` | `OPENROUTER_API_KEY` | `openrouter/auto` |

Override per-call model with `AI_MODEL_OVERRIDE` (fast) and `QUALITY_MODEL` (strong).

**`claude` (metered API, default):** calls the Anthropic API directly via `_chat_claude` in
`scripts/utils.py`. Requires `ANTHROPIC_API_KEY`. No Claude Code CLI/login and no subscription
session-window limit — every stage script's AI call runs independently. Also the only path
with prompt caching (`ai_chat_blocks()`).

**`claude_code` (subscription, no per-call billing):** routes AI through your logged-in
Claude Code subscription via the **Agent SDK** (`claude-agent-sdk`), through `_chat_claude_code`
in `scripts/utils.py`. No metered API key is used. Prerequisites: install the Claude Code
CLI, run `claude /login`, and `pip install claude-agent-sdk`. Caveats: **no prompt caching**
on this path, and `ANTHROPIC_API_KEY` must **not** be present in the environment (the SDK/CLI
would prefer it and bill metered) — `_chat_claude_code` pops it from `os.environ` before calling.
For headless auth (e.g. CI), run `claude setup-token` locally once (requires Pro/Max) and set
the resulting value as `CLAUDE_CODE_OAUTH_TOKEN` in the environment instead of `/login`.

**`gemini` / `codex` / `openrouter` (alternative metered APIs):** `gemini` and `codex` call
Google/OpenAI directly; `openrouter` calls [OpenRouter](https://openrouter.ai)'s
OpenAI-compatible endpoint, which fronts many vendors' models (Anthropic, OpenAI, Google,
Meta, ...) behind one `OPENROUTER_API_KEY` — set the actual model per tier via
`MODEL_OVERRIDES["openrouter"]` (ids look like `"anthropic/claude-3.5-sonnet"`,
`"openai/gpt-4o-mini"`; see https://openrouter.ai/models). All three are wired the same way
as `claude`/`claude_code` in `scripts/utils.py`'s `_BACKENDS` — no other code changes needed
to add a fourth in the future.

### Hybrid tiering (`FAST_PROVIDER` / `QUALITY_PROVIDER`)

Optional per-tier override, on top of the single `AI_PROVIDER` above — set in `config/settings.py`
or via env vars of the same name. `FAST_PROVIDER` covers stage 1 scoring + stage 3 outreach
(many small/bulk calls); `QUALITY_PROVIDER` covers stage 2 tailor + stage 5/6 (few, larger
calls). Both default to `AI_PROVIDER`, so this is a no-op unless explicitly set. Routing logic
lives in `_active_provider(quality: bool)` in `scripts/utils.py`.

Interactively, keep both on `"claude"` (metered) — the subscription's real cost is its shared
5-hour usage window, which competes with your own interactive Claude Code sessions. This
changes for an **unattended, off-hours run** (e.g. `.github/workflows/nightly-pipeline.yml`,
scheduled at midnight): nothing is competing for the subscription window then, so
`QUALITY_PROVIDER=claude_code` becomes free marginal capacity instead of a scarce resource,
while `FAST_PROVIDER=claude` keeps the bulk/many-small-call stages on the cheap, cached,
session-window-independent path. `_chat_claude_code` raises a clear error (not a silent hang)
if a call hits the subscription's usage cap — re-running is safe since stages are idempotent
via Notion status.

### Runtime override (`--ai-mode`)

`run.py --ai-mode {metered,hybrid,subscription}` sets `FAST_PROVIDER`/`QUALITY_PROVIDER` env
vars for that single process before any `config.settings` import — the interactive equivalent
of hand-setting those env vars, without editing `config/settings.py` or a `.env` file.
`--metered-provider {claude,codex,gemini,openrouter}` (default `claude`) picks which metered
backend fills the non-subscription tier(s): `metered` → that provider on both tiers,
`hybrid` → that provider on the fast tier + `claude_code` on quality, `subscription` →
`claude_code`/`claude_code` regardless of `--metered-provider`. E.g. `--ai-mode metered
--metered-provider openrouter` runs both tiers through OpenRouter for one run. It takes
precedence over `.env` for that run only and does not persist; the next run without the flag
reverts to config defaults. Omitting `--ai-mode` leaves today's behavior untouched,
including the nightly workflow, which never passes it and keeps its own env vars.

## Development Notes

- **Resume:** `config/resume.txt` must exist before any stage runs
- **Notion database schema:** the tracker DB (`NOTION_DB_ID`) must have these properties: `Job Title` (title), `Company` (rich_text), `Location` (rich_text), `Job URL` (url), `Status` (select — 14 options: Interested, Scraped, Reviewed, Resume Tailored, Applied, Outreach Sent, Interview Scheduled, Offer Received, **Retry**, plus the manual-only Disregard, Blacklist, Archived, Rejected, Human Review), `Date Scraped` (date), `ATS Match Score` (number), `Tailored Resume Link` (url), `Date Applied` (date), `Hiring Manager` (rich_text), `Hiring Manager LinkedIn` (url). The live DB also carries `Notes` (rich_text), `Referral Contact` (rich_text), and `Job ID` (unique_id), none of which any stage reads or writes. `_notion_write_job()` additionally writes `Posted Date` (date), `Source` (rich_text), `Applicant Count` (number), and `Salary Range` (rich_text) when present on the job dict — add these properties (exact names/types) for Step 6's multi-source fields to land; their absence doesn't break the write (each is only added to `props` when the job dict has a value), it just means those columns stay empty. `Sponsorship` (select — yes/no/unknown) and `Scoring Attempts` (number) back the stage 1 scoring-retry queue (see below) and are written the same optionally-present way. `Enrichment Attempts` (number) backs the "Interested" intake enrichment-retry ceiling the same optionally-present way (see below). `Missing Keywords` (rich_text, comma-separated) is written the same optionally-present way by stage 1's `score_jobs_batch()` results and read back by `db_get_jobs()`/`_page_to_job()` into a list — stage 2 reads it as a prioritization hint for tailoring (see below); its absence doesn't break either stage, it just means stage 2 has no Stage-1 hint to work from. **`Retry` is not auto-created by the Notion API — add it to the `Status` select's options by hand once**, or `db_update_status`/`db_add_job` calls that try to set it will silently fail to apply that property (the page still gets created/updated, just without the new status). The job description is **not** a property — it is cached in the page **body** (paragraph blocks) by `db_add_job` / `db_add_job_linked` and read back by `db_get_job_description()`.
- **"Interested" intake enrichment reliability:** `enrich_job_url()` (`scripts/sources.py`) returns `None` when a hand-picked job URL can't be enriched (e.g. `generic_url_fetch()`'s JSON-LD probe and raw-tag-stripped fallback both come up short on a JS-rendered career page). `ingest_interested_from_notion()` never scores against a blank JD — on a failed enrichment it increments `Enrichment Attempts` and leaves the row as `Interested` for the next `--ingest` run, mirroring `rescore_retry_jobs()`'s ceiling below. Once `Enrichment Attempts` exceeds `MAX_ENRICHMENT_ATTEMPTS` (`config/settings.py`, default 3), the row is promoted to `Scraped` with a `Notes` marker ("enrichment failed — add JD manually") instead of retried forever. `generic_url_fetch()` itself tries a schema.org `JobPosting` JSON-LD block (`<script type="application/ld+json">`) before falling back to raw `<title>`/tag-stripped text — many ATS-hosted and SEO-conscious career pages emit this even when the visible DOM is a client-rendered SPA shell, so it can recover a real `title`/`company`/`location`/`description` where the old tag-stripping fallback returned blank fields or too little text. If both the JSON-LD probe and the raw-text fallback come up short (a genuine client-rendered SPA shell with no server-rendered JobPosting data at all), it falls back once more to `_headless_fetch()` — a headless Chromium render via Playwright (optional dependency, see `requirements.txt`; run `playwright install chromium` after installing) — and retries the identical extraction against the hydrated HTML. `_headless_fetch()` returns `None` (never raises) if Playwright isn't installed or the render itself fails, so its absence/failure degrades to the exact same "treat as enrichment failure" behavior as before this fallback existed.
- **Stage 1 scoring reliability:** `score_jobs_batch()` never fabricates a placeholder score. On a failed AI call (after `ai_chat`'s own 3-attempt retry with backoff) or a URL missing from the response, that job comes back `scored: False` and is written to Notion as `Status = "Retry"` with an empty ATS score — no fabricated `50`. `rescore_retry_jobs()` runs at the top of every stage 1 `run()`, right after `ingest_interested_from_notion()`: it re-scores every `Retry` row from its already-cached JD body (**no repeat Apify call**), incrementing `Scoring Attempts` each pass. Once `Scoring Attempts` exceeds `MAX_SCORING_ATTEMPTS` (`config/settings.py`), the job is promoted to `Scraped` with an empty score rather than retried forever. The same scoring call also classifies `company_type` (`product | staffing_or_consulting | agency | unknown`); a job whose type is in `SKIP_COMPANY_TYPES` is dropped (logged `[STAFFING/AI]`) the same way a sponsorship-denying JD is — but only when `scored` is `True`, so an unscored/failed batch is never dropped on an `"unknown"` `company_type`. `ai_chat()`/`ai_chat_blocks()` in `scripts/utils.py` retry transient errors (timeouts, 429/5xx) with exponential backoff and raise `AIChatError` on final failure, or `AIUsageCapError` immediately (no blind retry) on a detected Claude Code subscription usage-cap error.
- **Stage 2 keyword hint + post-tailor verification:** `tailor_resumes_batch()`/`_tailor_resume_single()` pass each job's stored `missing_keywords` into the tailoring prompt as a hint to verify against the full JD, not a checklist to blindly inject — Stage 1's list comes from a truncated JD excerpt, so the model still does its own extraction from the full JD and may find more (or discard a Stage-1 hint that doesn't actually fit). After `save_resume()`, `run()` calls `verify_tailored_score()` (reuses stage 1's `score_jobs_batch()` contract against the *tailored* resume text) and logs `ATS: {before} → {after}`; if `after` is below `MIN_TAILORED_ATS_SCORE` (`config/settings.py`, default 75), it logs a `⚠` warning only — it does not retry tailoring or change Notion status, matching the pipeline's existing non-blocking "log it, human decides in Notion" pattern.
- **Output dirs:** Auto-created by `ensure_dirs()` on first run
- **Gmail optional:** Stage 4 `--send` requires `config/gmail_credentials.json` (Google Cloud OAuth)
- **All secrets are env-sourced:** every key in `config/settings.py` (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `HUNTER_API_KEY`) is read via `os.environ.get(...)` — never hardcode a live value into that file, even locally. Locally, `config/settings.py`'s `_load_local_env()` auto-loads a git-ignored `.env` in the repo root (copy `.env.example` → `.env`) before any of those `os.environ.get(...)` calls run; it's a no-op under `GITHUB_ACTIONS`, where the same keys come from repo secrets (`.github/workflows/nightly-pipeline.yml`) instead. `NOTION_SCRATCH_PAGE_ID` follows the same env-sourced pattern but is **optional** — see "Scratch-note intake" above — the feature it backs no-ops when it's unset, unlike the required keys in this list. `NOTION_DB_ID` is also env-overridable (`os.environ.get("NOTION_DB_ID", "") or "<default>"`), with the existing tracker id as the default so nothing changes for the current setup; a fork points at its own tracker by setting it in `.env` rather than editing the source.
- **`HUNTER_API_KEY` / `LEAD_ACTOR`:** only consumed by `scripts/spike_phase0_leads.py`, the Step 7 (communications subsystem) Phase 0 spike — not part of the 6-stage pipeline above. See `docs/backlog/step-7-communications-subsystem.md`.
- **DOCX resumes:** Stage 2 copies the base resume `.docx` (`RESUME_TEMPLATE_PATH`, default `config/Achyuth_Resume.docx`) and applies targeted `{old → new}` keyword edits **in-place** via `extract_docx_text()` / `apply_docx_edits()` in `scripts/render_docx.py`, preserving formatting (also writes a `.txt` mirror). The legacy Jinja2/`docxtpl` render path (`render_docx.render()` + `config/resume_template.docx`, scaffolded by `scripts/make_resume_template.py`) is no longer used by the default flow.

## Testing a Change

**Rule of thumb: every change ships with a test — no exceptions, for any agent working in this repo.**

1. Touched `scripts/*.py` or `run.py` logic? Add or update a pytest test under `tests/` in the
   same change, following the existing contract-test pattern (`patch_ai_chat`/`patch_notion_db`
   fakes from `tests/conftest.py`; see `tests/test_stage1_auto_review_gate.py` or
   `tests/test_stage2_sponsorship_gate.py` for reference). Run `pytest -v` — it's mocked, needs
   no API keys/Notion/Claude Code login, and finishes in ~1.5s — and make sure it's green before
   calling the change done.
2. Touched an AI prompt (stage 1 scoring, stage 2 tailoring, stage 3 outreach) or a model
   setting (`QUALITY_MODEL`, `AI_MODEL_OVERRIDE`)? A green pytest suite only proves the
   *plumbing* against mocked/recorded responses — it can't see judgment drift. Also run
   `python scripts/run_evals.py` (real API call, costs tokens — not part of `tests.yml`) against
   the hand-labeled dataset (`tests/eval_data/jobs.json`) and check score-hit-rate / keyword
   recall / tailoring ATS delta didn't regress. See "Step 9" in `docs/CHANGELOG.md` for exactly
   what it measures. `--tailor` adds the stage 2 before→after ATS delta if stage 2 changed.
3. Run `python run.py --setup` to verify config
4. Test on a single job: `python run.py --stage 2 --min-score 0` or `python run.py --stage 3 --company "Stripe"`
5. Check output files in `output/` (resumes, emails, guides are human-readable)
6. Verify the Notion jobs database rows updated (status/score/links)

## Troubleshooting

- **"Resume not found"** — Add file to `config/resume.txt`
- **Notion errors / empty results** — Notion is the primary store: check `NOTION_API_KEY` is set, the integration is **shared with the database**, and the DB has the properties listed under "Notion database schema" with exactly those names/types (a missing or mistyped property silently breaks queries/writes)
- **Apify timeouts** — Scraper polls 30×10s; network issues may need retry
- **Gmail send fails** — Requires `config/gmail_credentials.json` OAuth setup
