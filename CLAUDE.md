# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Job Search Pipeline** — Automated job search using Claude API (no N8N, no VPS required).

Scrapes LinkedIn via Apify, tailors resumes per job, drafts cold/warm outreach emails, generates interview prep guides, and negotiates offers. Progress tracked in Supabase (primary) with Notion as a visual mirror.

### Key Dependencies
- `anthropic` — Claude API (default provider)
- `supabase` — Primary data store (`supabase-py`)
- `notion-client` — Notion mirror (optional visual tracker)
- `google-generativeai` / `openai` — Alternative AI providers
- `requests` — HTTP client for Apify

## Architecture

### Two entry points

**`workflow.py`** (preferred) — Claude-native agentic orchestrator. Claude acts as the "brain" and calls tools (Python functions) as "hands." Uses prompt caching on the resume, streaming output, and an agentic loop up to 60 iterations. Supports `--task` flag.

**`run.py`** (legacy) — Simple stage runner that calls each `scripts/stage*.py` directly. Uses `--stage` flag.

### Pipeline stages

| Stage | File | Purpose |
|-------|------|---------|
| 1 | `scripts/stage1_scrape.py` | Scrape LinkedIn via Apify (+ ingest Notion "Interested" jobs), score against resume (ATS 0–100), save to Supabase/Notion as "Scraped" |
| 2 | `scripts/stage2_tailor.py` | Fetch "Reviewed" jobs, apply targeted ATS keyword edits in-place to the base `.docx`, save to `output/resumes/` |
| 3 | `scripts/stage3_outreach.py` | Draft cold/warm outreach emails, save to `output/outreach/` |
| 4 | `scripts/stage4_digest.py` | Generate morning HTML digest of ready-to-apply jobs |
| 5 | `scripts/stage5_interview_prep.py` | Generate HTML interview prep guide |
| 6 | `scripts/stage6_negotiate.py` | Research salary benchmarks and draft HTML negotiation brief |

### Data flow

```
Supabase jobs table  ←→  all stages (primary)
       ↕ mirror (optional)
Notion DB  ←  visual tracker only
```

Status pipeline: `Interested (manual intake) → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received`

### Two-step daily flow

The pipeline has a human review gate between scraping and tailoring:

1. **Scrape & review** — `python run.py` (or `python workflow.py`) runs stages 1 + 4: scrape LinkedIn, score, and emit a review digest of "Scraped" jobs. **Stop here.**
2. **Review in Notion** — open the tracker and set `Status = Reviewed` on jobs worth applying to.
3. **Evaluate** — `python run.py --evaluate` syncs the "Reviewed" jobs back to Supabase (`sync_notion_to_supabase()`), then runs stage 2 (tailor) → stage 3 (outreach drafts, non-interactive) → stage 4 (ready digest).

### Manual job intake ("Interested")

Jobs the user finds by hand (e.g. LinkedIn connections/suggestions) are added **in Notion**: create a row with Job Title, Company, Job URL and `Status = Interested`. On the next Stage 1 run (or `python run.py --ingest`), `ingest_interested_from_notion()` enriches each via Apify, scores it, links the Supabase row to the existing Notion page, and promotes it to "Scraped" — after which it behaves like any scraped job. Hand-picked jobs bypass the `SKIP_COMPANIES` / US-location / sponsorship filters.

### Shared utilities (`scripts/utils.py`)

- `ai_chat(prompt, system, max_tokens, quality)` — provider-agnostic chat; `claude_chat` is an alias
- `ai_chat_blocks(blocks, ...)` — Claude-only structured content blocks with `cache_control`
- `db_find_job_by_url()`, `db_add_job()`, `db_update_status()`, `db_get_jobs()`, `db_get_ready_to_apply()`, `db_get_job_by_company()`, `db_get_job_description()` — Supabase CRUD (all also mirror to Notion)
- `db_add_job_linked(job, notion_page_id)` — insert a Supabase row linked to an existing Notion page (manual "Interested" intake); promotes that page to "Scraped" without creating a duplicate
- `get_notion_jobs_by_status(status)` — read manually-added Notion rows by status; `sync_notion_to_supabase()` — pull "Reviewed" status from Notion into Supabase before `--evaluate`
- `load_resume()`, `ensure_dirs()`, `today()`, `parse_json_response()` — misc helpers

**Configuration:** `config/settings.py` — all API keys, user profile, target roles, AI model settings, output paths.

## Common Commands

```bash
# Preferred: Claude-native agentic workflow
python workflow.py                                               # Morning pipeline (stages 1–4)
python workflow.py --task scrape                                 # Stage 1 only
python workflow.py --task tailor --min-score 65                  # Stage 2, ATS ≥65
python workflow.py --task outreach --company "Stripe"            # Cold outreach
python workflow.py --task outreach --company "Google" --contact "Jane Doe" --contact-role "PM"
python workflow.py --task digest --send                          # Stage 4 + email
python workflow.py --task interview --company "Meta" --role "Senior PM"
python workflow.py --task negotiate --company "Stripe" --role "PM" --offer 185000

# Legacy stage runner
python run.py                                                    # Scrape + review digest (stages 1, 4) — STOP for review
python run.py --ingest                                          # Ingest only Notion "Interested" jobs → Scraped
python run.py --evaluate                                        # Sync "Reviewed" from Notion, then tailor + outreach + digest
python run.py --setup                                            # Verify config
python run.py --stage 2 --min-score 65
python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
python run.py --stage 5 --company "Meta" --role "Senior PM"
```

## Key Design Patterns

1. **Supabase-first** — All stages read/write Supabase. Notion is a passive mirror updated only when `NOTION_API_KEY` is set.
2. **Two-model setup** — `AI_MODEL_OVERRIDE` (fast/cheap, e.g. Haiku) for scraping/outreach; `QUALITY_MODEL` (e.g. Sonnet) for tailoring/interview prep/workflow. Both set in `config/settings.py`.
3. **Idempotent stages** — Duplicates skipped via `db_find_job_by_url()` (URL-based dedup in Supabase).
4. **Manual review gates** — A "Reviewed" gate sits between scraping and tailoring (user marks jobs in Notion before `--evaluate`). Outreach drafts are saved but not auto-sent; user reviews `output/outreach/` files first.
5. **Prompt caching** — `workflow.py` caches the resume in the system prompt across all agentic loop iterations. `utils.py` `ai_chat_blocks()` caches structured blocks for stage scripts.
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
| `"gemini"` | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| `"codex"` | `OPENAI_API_KEY` | `gpt-4o` |

Override per-call model with `AI_MODEL_OVERRIDE` (fast) and `QUALITY_MODEL` (strong).

## Development Notes

- **Resume:** `config/resume.txt` must exist before any stage runs
- **Supabase schema:** `jobs` table with columns: `id, job_title, company, location, job_url, status, date_scraped, ats_match_score, job_description, tailored_resume_link, date_applied, hiring_manager, hiring_manager_linkedin, notion_page_id` (`job_description` caches the JD so stages 2/5 skip re-fetching; add with `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_description text;` if upgrading)
- **Output dirs:** Auto-created by `ensure_dirs()` on first run
- **Gmail optional:** Stage 4 `--send` requires `config/gmail_credentials.json` (Google Cloud OAuth)
- **DOCX resumes:** Stage 2 copies the base resume `.docx` (`RESUME_TEMPLATE_PATH`, default `config/Achyuth_Resume.docx`) and applies targeted `{old → new}` keyword edits **in-place** via `extract_docx_text()` / `apply_docx_edits()` in `scripts/render_docx.py`, preserving formatting (also writes a `.txt` mirror). The legacy Jinja2/`docxtpl` render path (`render_docx.render()` + `config/resume_template.docx`, scaffolded by `scripts/make_resume_template.py`) is no longer used by the default flow.

## Testing a Change

1. Run `python run.py --setup` to verify config
2. Test on a single job: `python workflow.py --task tailor` or `python run.py --stage 3 --company "Stripe"`
3. Check output files in `output/` (resumes, emails, guides are human-readable)
4. Verify Supabase rows updated and (if enabled) Notion mirrored

## Troubleshooting

- **"Resume not found"** — Add file to `config/resume.txt`
- **Supabase errors** — Check `SUPABASE_URL` and `SUPABASE_KEY` in `config/settings.py`; ensure `jobs` table schema matches `db_add_job()` column names
- **Notion silent failures** — Notion writes are fire-and-forget (`except: pass`); check `NOTION_API_KEY` and that the integration is shared with the DB
- **Apify timeouts** — Scraper polls 30×10s; network issues may need retry
- **Gmail send fails** — Requires `config/gmail_credentials.json` OAuth setup
