# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Job Search Pipeline** — Automated job search using Claude API (no N8N, no VPS required).

Scrapes LinkedIn via Apify, tailors resumes per job, drafts cold/warm outreach emails, generates interview prep guides, and negotiates offers. Progress is tracked in **Notion** (the single source of truth — the job tracker database).

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
| 1 | `scripts/stage1_scrape.py` | Scrape LinkedIn via Apify (+ ingest Notion "Interested" jobs), score against resume (ATS 0–100), save to Notion as "Scraped" |
| 2 | `scripts/stage2_tailor.py` | Fetch "Reviewed" jobs, apply targeted ATS keyword edits in-place to the base `.docx`, save to `output/resumes/` |
| 3 | `scripts/stage3_outreach.py` | Draft cold/warm outreach emails, save to `output/outreach/` |
| 4 | `scripts/stage4_digest.py` | Generate morning HTML digest of ready-to-apply jobs |
| 5 | `scripts/stage5_interview_prep.py` | Generate HTML interview prep guide |
| 6 | `scripts/stage6_negotiate.py` | Research salary benchmarks and draft HTML negotiation brief |

### Data flow

```
Notion jobs database  ←→  all stages (primary, single source of truth)
       ↑
Apify (LinkedIn scrape)  →  stage 1
```

Status pipeline: `Interested (manual intake) → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received`

Off-pipeline states (`Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review`) exist as
select options and are set **by hand** — no stage writes them. Since `db_get_jobs()` filters on an
exact status, a row parked in one of them is simply never picked up. Dedup is the exception: it
spans every status, so a `Disregard`d job is not re-scraped.

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
- `db_get_all_jobs()` — one unfiltered paginated read of every row (`page_id, title, company, location, url, status, ats_score`); backs Stage 1's in-memory dedup. Returns `[]` on failure
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
3. **Idempotent stages** — Duplicates skipped by exact Job URL match. Stage 1 reads every existing row once via `db_get_all_jobs()` and dedups against that in-memory URL set (spanning *all* statuses), rather than querying Notion per listing. `db_find_job_by_url()` remains for one-off lookups (e.g. "Interested" intake).
4. **Manual review gates** — A "Reviewed" gate sits between scraping and tailoring (user marks jobs in Notion before `--evaluate`). Outreach drafts are saved but not auto-sent; user reviews `output/outreach/` files first.
5. **Prompt caching** — `utils.py` `ai_chat_blocks()` caches structured blocks, but only on the metered `"claude"` provider; every other provider joins the blocks into plain text. On the `claude_code` path the CLI manages its own caching.
6. **Adding a provider** — Add a `_chat_<name>` function to `_BACKENDS` dict in `scripts/utils.py`. No other changes needed.

## Stage 1 Filters

Two settings in `config/settings.py` control what gets saved:
- `SKIP_COMPANIES` — substring denylist for consulting/staffing firms; grows over time
- `EXCLUDE_NO_SPONSORSHIP = True` — skips jobs that explicitly deny visa sponsorship

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

## Development Notes

- **Resume:** `config/resume.txt` must exist before any stage runs
- **Notion database schema:** the tracker DB (`NOTION_DB_ID`) must have these properties: `Job Title` (title), `Company` (rich_text), `Location` (rich_text), `Job URL` (url), `Status` (select — 13 options: Interested, Scraped, Reviewed, Resume Tailored, Applied, Outreach Sent, Interview Scheduled, Offer Received, plus the manual-only Disregard, Blacklist, Archived, Rejected, Human Review), `Date Scraped` (date), `ATS Match Score` (number), `Tailored Resume Link` (url), `Date Applied` (date), `Hiring Manager` (rich_text), `Hiring Manager LinkedIn` (url). The live DB also carries `Notes` (rich_text), `Referral Contact` (rich_text), and `Job ID` (unique_id), none of which any stage reads or writes. The job description is **not** a property — it is cached in the page **body** (paragraph blocks) by `db_add_job` / `db_add_job_linked` and read back by `db_get_job_description()`.
- **Output dirs:** Auto-created by `ensure_dirs()` on first run
- **Gmail optional:** Stage 4 `--send` requires `config/gmail_credentials.json` (Google Cloud OAuth)
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
