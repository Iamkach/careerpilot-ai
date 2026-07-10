# Configuration & Setup Guide

How to configure and run the **AI Job Search Pipeline** from a clean checkout.

There are two entry points that share the same config and stages:

- `run.py` — legacy stage runner (explicit CLI flags per stage)
- `workflow.py` — Claude-native agentic orchestrator (Claude decides which tools/stages to call)

Both read everything from `config/settings.py`.

---

## 1. Prerequisites

- **Python 3.9+**
- Accounts / keys (only the ones for the features you use):
  - A Claude Code subscription (default provider `claude_code`) **or** an AI provider key — Anthropic **or** Gemini **or** OpenAI
  - **Apify** token (LinkedIn scraping) — free tier works
  - **Notion** integration key (primary data store — the job tracker database)
  - **Gmail** OAuth credentials (optional — emailed digest)

---

## 2. Install dependencies

Install the SDK for your chosen provider plus the shared packages. `run.py --setup`
expects `notion_client` and `requests` in addition to the provider SDK. Or just
`pip install -r requirements.txt`.

```bash
# Claude Code subscription (default provider: claude_code)
pip install claude-agent-sdk notion-client requests docxtpl

# Gemini
pip install google-generativeai notion-client requests docxtpl

# OpenAI / Codex
pip install openai notion-client requests docxtpl
```

> `docxtpl` powers the stage-2 `.docx` resume rendering (see step 3b).

> `workflow.py` runs on the **Agent SDK** (`claude-agent-sdk`) over your Claude Code
> subscription, so install it if you plan to use the agentic orchestrator.

---

## 3. Add your resume

Create `config/resume.txt` and paste your full resume as plain text (or Markdown).
This file is required — every stage that touches the resume reads it from here.

```
config/resume.txt
```

---

## 3b. Add your base resume `.docx` (stage 2 source)

Stage 2 does **not** render from a Jinja2 template. It takes your real, already-formatted
resume `.docx`, copies it per job, and applies targeted `{old → new}` ATS keyword edits
**in-place** — so every tailored resume keeps your exact original formatting and only the
wording changes.

Put your resume at `config/Achyuth_Resume.docx` (path set by `RESUME_TEMPLATE_PATH` in
`config/settings.py`). It's a plain Word document — **no placeholder tags required**.

```python
RESUME_TEMPLATE_PATH = "config/Achyuth_Resume.docx"   # your base resume .docx
```

Stage 2 reads it via `extract_docx_text()` and edits it via `apply_docx_edits()` (both in
`scripts/render_docx.py`), then writes `output/resumes/*.docx` plus a `.txt` mirror. If the
`.docx` is missing, stage 2 falls back to `config/resume.txt` and writes a `.txt` only.

> The base resume is git-ignored (personal content) — add your own on each checkout.
> (`scripts/make_resume_template.py` + the legacy `docxtpl` render path still exist but are
> not used by the default tailoring flow.)

---

## 4. Fill in `config/settings.py`

Open `config/settings.py` and complete each section.

### Your profile
```python
YOUR_NAME  = "Jane Doe"
YOUR_EMAIL = "jane@example.com"
YOUR_BIO   = "Two-line professional bio used in outreach emails"
```

### Job search targets
```python
TARGET_ROLES     = ["Product Manager", "Senior Product Manager", "Group PM"]
# Search is always US-wide. Jobs are filtered to US locations post-scrape.
TARGET_COMPANIES = ["Google", "Meta", "Stripe", "Notion", "Figma"]
```

### AI provider
```python
AI_PROVIDER       = "claude_code"   # "claude_code" | "claude" | "gemini" | "codex"
AI_MODEL_OVERRIDE = ""              # leave blank to use the provider default
```

| `AI_PROVIDER`  | Default model       | Key to set                             |
|----------------|---------------------|----------------------------------------|
| `claude_code`  | `sonnet`            | Claude Code subscription (`claude /login`) |
| `claude`       | `claude-opus-4-6`   | `ANTHROPIC_API_KEY`                    |
| `gemini`       | `gemini-2.0-flash`  | `GEMINI_API_KEY`                       |
| `codex`        | `gpt-4o`            | `OPENAI_API_KEY`                       |

> **`claude_code` (default)** routes all AI through your logged-in Claude Code
> subscription via the Agent SDK — no metered API key is used. Prerequisites: install
> the Claude Code CLI, run `claude /login`, and `pip install claude-agent-sdk`.
> **`ANTHROPIC_API_KEY` must NOT be present in the environment** or the SDK/CLI would
> prefer it and bill metered.

### API keys
```python
ANTHROPIC_API_KEY = "***REMOVED-SECRET***"   # https://console.anthropic.com        (provider: claude only)
GEMINI_API_KEY    = "..."   # https://aistudio.google.com/apikey   (provider: gemini)
OPENAI_API_KEY    = "***REMOVED-SECRET***"   # https://platform.openai.com/api-keys (provider: codex)
APIFY_API_TOKEN   = "***REMOVED-SECRET***"   # https://apify.com (free token)
NOTION_API_KEY    = "***REMOVED-SECRET***"   # https://www.notion.so/my-integrations (PRIMARY data store)
```
Under the default `claude_code` provider, no AI key is needed. Otherwise set only the
key matching `AI_PROVIDER`.

### Notion (primary data store — required)
```python
NOTION_API_KEY = "***REMOVED-SECRET***"   # the integration token
NOTION_DB_ID   = "2ac0907e693744698a1c748d37774a07"   # already set — your tracker DB
```
Notion is the single source of truth. Create the integration at
https://www.notion.so/my-integrations and **share your tracker database with it** —
all reads and writes go through the Notion API (see step 5 for the required schema).

### Gmail (optional — emailed digest)
```python
GMAIL_CREDENTIALS_PATH = "config/gmail_credentials.json"
DIGEST_RECIPIENT_EMAIL = YOUR_EMAIL
```
Only needed for `--send` on stage 4 (see step 6).

---

## 5. Set up the Notion database schema (once)

Notion is the primary data store. Your tracker DB (`NOTION_DB_ID`) must have these
properties — **names and types must match exactly** (a missing or mistyped property
silently breaks queries/writes):

| Property | Type | Notes |
|----------|------|-------|
| `Job Title` | title | |
| `Company` | rich_text | |
| `Location` | rich_text | |
| `Job URL` | url | used for URL-based dedup |
| `Status` | select | pipeline: `Interested`, `Scraped`, `Reviewed`, `Resume Tailored`, `Applied`, `Outreach Sent`, `Interview Scheduled`, `Offer Received`<br>manual-only: `Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review` |
| `ATS Match Score` | number | |
| `Date Scraped` | date | |
| `Tailored Resume Link` | url | |
| `Date Applied` | date | |
| `Hiring Manager` | rich_text | |
| `Hiring Manager LinkedIn` | url | |

> The full **job description is not a property** — it is cached in the page **body**
> (paragraph blocks) by `db_add_job` / `db_add_job_linked` and read back by
> `db_get_job_description()`.

Create each `Status` select option once (type it into the select to create it), and
make sure the Notion integration is **shared with the database**.

### Notion intake & review statuses

Two statuses are set by you in Notion, not by the scripts:
- **`Interested`** — add a job by hand (Job Title + Company + Job URL); the next scrape
  ingests, enriches, and scores it (`python run.py --ingest` runs only this).
- **`Reviewed`** — approve a scraped job for tailoring; `python run.py --evaluate` reads
  these straight from Notion and runs stages 2–4.

In the Notion DB's **Status** select, add `Interested` and `Reviewed` as options (type them
once into the select to create them).

---

## 6. (Optional) Gmail digest setup

1. Create a Google Cloud project and enable the **Gmail API**.
2. Create OAuth client credentials and download the JSON.
3. Save it to `config/gmail_credentials.json`.
4. Use `--send` on stage 4 to email the digest.

---

## 7. Verify the setup

```bash
python run.py --setup
```

This prints a ✓/✗ checklist for the active provider key, Apify token, Notion API key
(primary data store), Notion DB ID, resume file, and installed packages. Fix any ✗
before running. Output dirs under `output/` are auto-created on first run.

---

## 8. Run it

### Legacy stage runner — `run.py`
```bash
python run.py                                   # Step 1: scrape + review digest (stages 1, 4) — then review in Notion
python run.py --ingest                          # ingest only Notion "Interested" jobs → "Scraped"
python run.py --evaluate                        # Step 2: sync "Reviewed", then tailor + outreach + digest
python run.py --stage 1                          # scrape LinkedIn → store
python run.py --stage 2 --min-score 65           # tailor Reviewed resumes (≥65 ATS only)
python run.py --stage 3 --company "Stripe"       # cold outreach
python run.py --stage 3 --company "Google" --contact "Jane Doe"   # warm referral
python run.py --stage 4 --send                   # digest, emailed via Gmail
python run.py --stage 5 --company "Meta" --role "Senior PM"       # interview prep
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000   # negotiation
```

### Claude agentic orchestrator — `workflow.py`
```bash
python workflow.py                               # morning pipeline (stages 1-4)
python workflow.py --task scrape
python workflow.py --task tailor --min-score 65
python workflow.py --task outreach --company "Stripe"
python workflow.py --task digest --send
python workflow.py --task interview --company "Meta" --role "Senior PM"
python workflow.py --task negotiate --company "Stripe" --role "PM" --offer 185000
```

---

## 9. Outputs

| Path | Contents |
|------|----------|
| `output/resumes/` | Tailored resumes per job — `.docx` (in-place edits of your base resume) + `.txt` mirror |
| `output/outreach/` | Cold + warm email drafts (`.txt`) — reviewed before sending |
| `output/prep_guides/` | Interview prep guides (`.html`) |
| `output/negotiation/` | Negotiation briefs (`.html`) |
| `output/digest_YYYY-MM-DD.html` | Daily digest |

Status pipeline (tracked in Notion, the single source of truth):
`Interested (manual intake) → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received`

Five further options — `Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review` — are set
by hand and written by no stage. A row parked in one of them drops out of the pipeline but is still
seen by dedup, so it will not be re-scraped.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Resume not found` | Add `config/resume.txt` |
| Provider key ✗ | Set the key matching `AI_PROVIDER`, or use `claude_code` (`claude /login`) |
| Notion errors / empty results | Set `NOTION_API_KEY`, share the DB with the integration, and match the schema in step 5 |
| `notion-client` version error | Pin `notion-client>=2.2.1,<2.6` (2.6+/3.x dropped `databases.query`) |
| Apify timeouts | Scraper retries 30×10s; retry on network errors |
| Gmail send fails | Ensure `config/gmail_credentials.json` exists (OAuth) |
| Duplicate jobs | Dedup is by job URL; check the `Job URL` property for trailing slashes / query params |
