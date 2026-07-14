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
| 1 | `scripts/stage1_scrape.py` | Scrape every source in `ENABLED_SOURCES` via `scripts/sources.py` (+ ingest Notion "Interested" jobs), score against resume (ATS 0–100), save to Notion as "Scraped" |
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

The pipeline has a human review gate between scraping and tailoring:

1. **Scrape & review** — `python run.py` runs stages 1 + 4: scrape LinkedIn, score, and emit a review digest of "Scraped" jobs. **Stop here.**
2. **Review in Notion** — open the tracker and set `Status = Reviewed` on jobs worth applying to.
3. **Evaluate** — `python run.py --evaluate` reads the "Reviewed" jobs straight from Notion, then runs stage 2 (tailor) → stage 3 (outreach drafts, non-interactive) → stage 4 (ready digest).

### Manual job intake ("Interested")

Jobs the user finds by hand (e.g. LinkedIn connections/suggestions) are added **in Notion**: create a row with Job Title, Company, Job URL and `Status = Interested`. On the next Stage 1 run (or `python run.py --ingest`), `ingest_interested_from_notion()` enriches each via Apify, scores it, and promotes that same Notion page to "Scraped" (caching the JD in the page body) — after which it behaves like any scraped job. Hand-picked jobs bypass the `SKIP_COMPANIES` / US-location / sponsorship filters.

### Shared utilities (`scripts/utils.py`)

- `ai_chat(prompt, system, max_tokens, quality)` — provider-agnostic chat; `claude_chat` is an alias
- `ai_chat_blocks(blocks, ...)` — Claude-only structured content blocks with `cache_control`
- `db_find_job_by_url()`, `db_add_job()`, `db_update_status()`, `db_get_jobs()`, `db_get_all_jobs()`, `db_get_ready_to_apply()`, `db_get_job_by_company()`, `db_get_job_description()` — Notion-backed CRUD (`page_id`/`id` is the Notion page id; the JD is cached in the page body via paragraph blocks)
- `db_get_all_jobs()` — one unfiltered paginated read of every row (`page_id, title, company, location, url, status, ats_score`); backs Stage 1's in-memory dedup (URL set + fingerprint set). **Raises `RuntimeError` on a failed read** — Stage 1 aborts the scrape rather than treating a failed read as an empty DB (which would mass-duplicate the tracker)
- `db_add_job_linked(job, notion_page_id)` — promote an existing manually-added Notion page ("Interested" intake) to "Scraped" in place (no duplicate page); caches the JD in its body
- `get_notion_jobs_by_status(status)` — read Notion rows by status. `sync_notion_to_supabase()` is now a no-op kept for compatibility (Notion is the store)
- `load_resume()`, `ensure_dirs()`, `today()`, `parse_json_response()` — misc helpers

**Configuration:** `config/settings.py` — all API keys, user profile, target roles, AI model settings, output paths.

## Common Commands

```bash
python run.py                                                    # Scrape + review digest (stages 1, 4) — STOP for review
python run.py --ingest                                          # Ingest only Notion "Interested" jobs → Scraped
python run.py --evaluate                                        # Sync "Reviewed" from Notion, then tailor + outreach + digest
python run.py --setup                                            # Verify config
python run.py --stage 1                                          # Scrape only (also ingests "Interested")
python run.py --stage 2 --min-score 65
python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
python run.py --stage 4 --send
python run.py --stage 5 --company "Meta" --role "Senior PM"
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000
```

## Key Design Patterns

1. **Notion-first** — Notion is the single source of truth. All stages read/write the Notion jobs database via the `db_*` helpers; `NOTION_API_KEY` + DB sharing are required.
2. **Two-model setup** — `AI_MODEL_OVERRIDE` (fast/cheap, e.g. Haiku) for scraping/outreach; `QUALITY_MODEL` (e.g. Sonnet) for tailoring/interview prep/negotiation. Both set in `config/settings.py`.
3. **Idempotent stages** — Duplicates skipped by exact Job URL match **and** by company+title fingerprint (`job_fingerprint()` in `scripts/sources.py`, catching the same req posted to multiple sources). Stage 1 reads every existing row once via `db_get_all_jobs()` and dedups against that in-memory URL/fingerprint set (excluding the not-yet-settled `Interested` status), rather than querying Notion per listing. `db_find_job_by_url()` remains for one-off lookups (e.g. "Interested" intake).
4. **Manual review gates** — A "Reviewed" gate sits between scraping and tailoring (user marks jobs in Notion before `--evaluate`). Outreach drafts are saved but not auto-sent; user reviews `output/outreach/` files first.
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

## Development Notes

- **Resume:** `config/resume.txt` must exist before any stage runs
- **Notion database schema:** the tracker DB (`NOTION_DB_ID`) must have these properties: `Job Title` (title), `Company` (rich_text), `Location` (rich_text), `Job URL` (url), `Status` (select — 14 options: Interested, Scraped, Reviewed, Resume Tailored, Applied, Outreach Sent, Interview Scheduled, Offer Received, **Retry**, plus the manual-only Disregard, Blacklist, Archived, Rejected, Human Review), `Date Scraped` (date), `ATS Match Score` (number), `Tailored Resume Link` (url), `Date Applied` (date), `Hiring Manager` (rich_text), `Hiring Manager LinkedIn` (url). The live DB also carries `Notes` (rich_text), `Referral Contact` (rich_text), and `Job ID` (unique_id), none of which any stage reads or writes. `_notion_write_job()` additionally writes `Posted Date` (date), `Source` (rich_text), `Applicant Count` (number), and `Salary Range` (rich_text) when present on the job dict — add these properties (exact names/types) for Step 6's multi-source fields to land; their absence doesn't break the write (each is only added to `props` when the job dict has a value), it just means those columns stay empty. `Sponsorship` (select — yes/no/unknown) and `Scoring Attempts` (number) back the stage 1 scoring-retry queue (see below) and are written the same optionally-present way. **`Retry` is not auto-created by the Notion API — add it to the `Status` select's options by hand once**, or `db_update_status`/`db_add_job` calls that try to set it will silently fail to apply that property (the page still gets created/updated, just without the new status). The job description is **not** a property — it is cached in the page **body** (paragraph blocks) by `db_add_job` / `db_add_job_linked` and read back by `db_get_job_description()`.
- **Stage 1 scoring reliability:** `score_jobs_batch()` never fabricates a placeholder score. On a failed AI call (after `ai_chat`'s own 3-attempt retry with backoff) or a URL missing from the response, that job comes back `scored: False` and is written to Notion as `Status = "Retry"` with an empty ATS score — no fabricated `50`. `rescore_retry_jobs()` runs at the top of every stage 1 `run()`, right after `ingest_interested_from_notion()`: it re-scores every `Retry` row from its already-cached JD body (**no repeat Apify call**), incrementing `Scoring Attempts` each pass. Once `Scoring Attempts` exceeds `MAX_SCORING_ATTEMPTS` (`config/settings.py`), the job is promoted to `Scraped` with an empty score rather than retried forever. The same scoring call also classifies `company_type` (`product | staffing_or_consulting | agency | unknown`); a job whose type is in `SKIP_COMPANY_TYPES` is dropped (logged `[STAFFING/AI]`) the same way a sponsorship-denying JD is — but only when `scored` is `True`, so an unscored/failed batch is never dropped on an `"unknown"` `company_type`. `ai_chat()`/`ai_chat_blocks()` in `scripts/utils.py` retry transient errors (timeouts, 429/5xx) with exponential backoff and raise `AIChatError` on final failure, or `AIUsageCapError` immediately (no blind retry) on a detected Claude Code subscription usage-cap error.
- **Output dirs:** Auto-created by `ensure_dirs()` on first run
- **Gmail optional:** Stage 4 `--send` requires `config/gmail_credentials.json` (Google Cloud OAuth)
- **All secrets are env-sourced:** every key in `config/settings.py` (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `HUNTER_API_KEY`) is read via `os.environ.get(...)` — never hardcode a live value into that file, even locally.
- **`HUNTER_API_KEY` / `LEAD_ACTOR`:** only consumed by `scripts/spike_phase0_leads.py`, the Step 7 (communications subsystem) Phase 0 spike — not part of the 6-stage pipeline above. See `docs/backlog/step-7-communications-subsystem.md`.
- **DOCX resumes:** Stage 2 copies the base resume `.docx` (`RESUME_TEMPLATE_PATH`, default `config/Achyuth_Resume.docx`) and applies targeted `{old → new}` keyword edits **in-place** via `extract_docx_text()` / `apply_docx_edits()` in `scripts/render_docx.py`, preserving formatting (also writes a `.txt` mirror). The legacy Jinja2/`docxtpl` render path (`render_docx.render()` + `config/resume_template.docx`, scaffolded by `scripts/make_resume_template.py`) is no longer used by the default flow.

## Testing a Change

1. Run `python run.py --setup` to verify config
2. Test on a single job: `python run.py --stage 2 --min-score 0` or `python run.py --stage 3 --company "Stripe"`
3. Check output files in `output/` (resumes, emails, guides are human-readable)
4. Verify the Notion jobs database rows updated (status/score/links)

## Troubleshooting

- **"Resume not found"** — Add file to `config/resume.txt`
- **Notion errors / empty results** — Notion is the primary store: check `NOTION_API_KEY` is set, the integration is **shared with the database**, and the DB has the properties listed under "Notion database schema" with exactly those names/types (a missing or mistyped property silently breaks queries/writes)
- **Apify timeouts** — Scraper polls 30×10s; network issues may need retry
- **Gmail send fails** — Requires `config/gmail_credentials.json` OAuth setup
