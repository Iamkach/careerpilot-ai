# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Job Search Pipeline** — Automated job search using Claude API (no N8N, no VPS required).

Scrapes LinkedIn via Apify, tailors resumes per job, drafts cold/warm outreach emails, generates interview prep guides, and negotiates offers. All progress tracked in a Notion database.

### Key Dependencies
- `anthropic` — Claude API (if `AI_PROVIDER = "claude"`, default)
- `google-generativeai` — Gemini API (if `AI_PROVIDER = "gemini"`)
- `openai` — OpenAI/Codex API (if `AI_PROVIDER = "codex"`)
- `notion-client` — Notion database tracking
- `requests` — HTTP client for Apify

## Architecture

The pipeline is split into **6 modular stages**, each with its own script:

| Stage | File | Purpose |
|-------|------|---------|
| 1 | `scripts/stage1_scrape.py` | Scrape LinkedIn jobs via Apify, score against resume using Claude, save to Notion |
| 2 | `scripts/stage2_tailor.py` | Fetch "Scraped" jobs, rewrite resume per JD using Claude, save to `output/resumes/` |
| 3 | `scripts/stage3_outreach.py` | Draft cold/warm outreach emails using Claude, save to `output/outreach/` |
| 4 | `scripts/stage4_digest.py` | Generate morning HTML digest of ready-to-apply jobs, optionally email via Gmail |
| 5 | `scripts/stage5_interview_prep.py` | Generate interview prep guide (HTML) using Claude |
| 6 | `scripts/stage6_negotiate.py` | Research salary benchmarks and draft negotiation script (HTML) using Claude |

**Master entry point:** `run.py` orchestrates stages via CLI arguments.

**Shared utilities:** `scripts/utils.py` contains:
- `get_claude()` / `claude_chat()` — Claude API client wrapper
- `get_notion()` — Notion client
- `notion_add_job()`, `notion_update_status()` — Notion tracker helpers
- Resume loading, output dir setup, date/logging helpers

**Configuration:** `config/settings.py` — all API keys, user info, target roles, paths

**Central tracker:** Notion database at `NOTION_DB_ID` with status pipeline:
```
Scraped → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received
```

## Common Commands

```bash
# Full morning pipeline (stages 1–4)
python run.py

# Verify setup & check dependencies
python run.py --setup

# Individual stages
python run.py --stage 1                                    # Scrape
python run.py --stage 2 --min-score 65                    # Tailor (only ≥65 ATS match)
python run.py --stage 3 --company "Stripe"                # Cold outreach
python run.py --stage 3 --company "Google" --contact "Jane Doe"  # Warm referral
python run.py --stage 4 --send                             # Email digest to Gmail
python run.py --stage 5 --company "Meta" --role "Senior PM"      # Interview prep
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000  # Negotiation
```

## Key Design Patterns

1. **Idempotent scripts** — All stages are safe to re-run; duplicates are skipped (checked via Notion job URL)
2. **Claude-heavy** — Resume tailoring, email drafting, ATS matching, interview prep all use Claude Opus 4.6
3. **Notion as source of truth** — Each stage reads/writes Notion DB to track progress
4. **Manual review gates** — Stage 3 outreach drafts are saved but not auto-sent (user reviews first)
5. **Output files for offline use** — Resumes, emails, prep guides saved as `.txt` or `.html` for review/sharing

## Switching AI Provider

Set `AI_PROVIDER` in `config/settings.py` and add the matching API key:

| `AI_PROVIDER` | Key setting | Install |
|---|---|---|
| `"claude"` (default) | `ANTHROPIC_API_KEY` | `pip install anthropic` |
| `"gemini"` | `GEMINI_API_KEY` | `pip install google-generativeai` |
| `"codex"` | `OPENAI_API_KEY` | `pip install openai` |

Optionally override the model with `AI_MODEL_OVERRIDE = "gpt-4o-mini"` (any model name the provider accepts).

All stages call `ai_chat()` in `scripts/utils.py` — `claude_chat` is an alias for backward compatibility. The provider dispatch lives in `_BACKENDS` dict; adding a new provider means adding one `_chat_<name>` function there.

## Development Notes

- **Resume path:** Must be added to `config/resume.txt` before any stage runs
- **API keys:** Set in `config/settings.py` before running (active provider + Apify + Notion)
- **Notion DB setup:** Already created — just paste your integration key
- **Output dirs:** Auto-created by `ensure_dirs()` on first run
- **Notion queries:** Use status filters and URL-based dedup to avoid re-processing
- **Gmail optional:** Stage 4 can email digest if OAuth credentials are set up

## Testing a Change

For changes to Claude prompts, resume tailoring logic, or email drafting:
1. Run `python run.py --setup` to verify config
2. Test on a single job: e.g., `python run.py --stage 2 --company "Google"` or `python run.py --stage 3 --company "Stripe" --contact "Jane Doe"`
3. Check output files in `output/` directory (resumes, emails, guides are human-readable)
4. Verify Notion updates: each stage should update the Status field for traced jobs

## Troubleshooting

- **"Resume not found"** — Add file to `config/resume.txt`
- **"Notion API key missing"** — Check `config/settings.py`
- **Apify timeouts** — Scraper waits 30×10s before failing; network issues may require retry
- **Gmail send fails** — Stage 4 `--send` requires `config/gmail_credentials.json` (OAuth setup in Google Cloud Console)
- **Duplicate jobs** — Stage 1 deduplicates via `notion_find_job_by_url()`; if duplicates appear, check Notion filter logic
