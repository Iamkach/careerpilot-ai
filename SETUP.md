# Configuration & Setup Guide

How to configure and run the **AI Job Search Pipeline** from a clean checkout.

`run.py` is the single entry point — a deterministic stage runner (explicit CLI flags per
stage). It reads everything from `config/settings.py`.

---

## 1. Prerequisites

- **Python 3.9+**
- Accounts / keys (only the ones for the features you use):
  - An AI provider key — Anthropic (default) **or** Gemini **or** OpenAI **or** a Claude Code subscription
  - **Apify** token (LinkedIn + Indeed scraping) — free tier works. **Set it via environment
    variable only** (`APIFY_API_TOKEN`) — `config/settings.py` reads it with `os.environ.get(...)`,
    same as every other key; never paste a live token into the file itself.
  - **Notion** integration key (primary data store — the job tracker database)
  - **Gmail** OAuth credentials (optional — emailed digest)
  - **Hunter.io** API key (optional — only needed for the Step 7 communications-subsystem
    spike script, `scripts/spike_phase0_leads.py`; not required for the core 6-stage pipeline)
  - No key needed for Greenhouse/Lever/Ashby board sourcing — those are free, keyless JSON APIs

---

## 2. Install dependencies

Install the SDK for your chosen provider plus the shared packages. `run.py --setup`
expects `notion_client` and `requests` in addition to the provider SDK. Or just
`pip install -r requirements.txt`.

```bash
# Claude metered API (default provider: claude)
pip install anthropic notion-client requests docxtpl

# Gemini
pip install google-generativeai notion-client requests docxtpl

# OpenAI / Codex
pip install openai notion-client requests docxtpl
```

> `docxtpl` powers the stage-2 `.docx` resume rendering (see step 3b).

> `AI_PROVIDER="claude_code"` is also supported (runs on the **Agent SDK**,
> `claude-agent-sdk`, over your Claude Code subscription instead of metered billing) —
> install `claude-agent-sdk` if you switch to it. Its trade-off is no prompt caching and
> a subscription session-window limit on long runs.

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
`TARGET_COMPANIES` seeds two things: Apify keyword searches and — via
`scripts/sources.py`'s `discover_tokens()` — a one-time probe of each company's
Greenhouse/Lever/Ashby board (see "Multi-source sourcing" below). It's unioned at runtime
with every distinct company already in your Notion DB, so it grows on its own as you scrape.

### Multi-source sourcing (stage 1)
```python
ENABLED_SOURCES   = ["linkedin", "indeed", "greenhouse", "lever", "ashby"]
MAX_JOB_AGE_DAYS  = 14      # drop postings older than this (by posted_date)
DROP_UNDATED_JOBS = False   # keep sources that don't expose a date, by default
```
Stage 1 pulls from a registry of sources instead of just LinkedIn:
- `linkedin`, `indeed` — Apify actors, searched per `TARGET_ROLES` (need `APIFY_API_TOKEN`)
- `greenhouse`, `lever`, `ashby` — free, keyless JSON APIs, crawled per company in
  `TARGET_COMPANIES` (no token needed)

**One-time pre-processing the first time you enable a board source:** on its first run,
`discover_tokens()` probes each seed company's Greenhouse/Lever/Ashby board and caches the
result (hit or miss) to `config/ats_tokens.json`, so later runs don't re-probe (a null entry
is retried after ~30 days). Greenhouse hits are self-verified against the company name in the
response; **Lever/Ashby auto-accepted tokens are logged loudly** the first time they're
found — skim that log output once and remove any mismatched entry from
`config/ats_tokens.json` by hand if a token was auto-accepted for the wrong company. No
action needed if you only run `ENABLED_SOURCES = ["linkedin", "indeed"]`.

Same-job duplicates posted to multiple sources (e.g. Greenhouse + LinkedIn) are collapsed by
`job_fingerprint()`, keeping the ATS-board copy (fuller JD, real date, direct-apply URL) over
the LinkedIn/Indeed copy — see `SOURCE_PRIORITY` in `scripts/sources.py`.

### AI provider
```python
AI_PROVIDER       = "claude"        # "claude" | "claude_code" | "gemini" | "codex"
AI_MODEL_OVERRIDE = ""              # leave blank to use the provider default
```

| `AI_PROVIDER`  | Default model       | Key to set                             |
|----------------|---------------------|----------------------------------------|
| `claude`       | `claude-opus-4-6`   | `ANTHROPIC_API_KEY`                    |
| `claude_code`  | `sonnet`            | Claude Code subscription (`claude /login`) |
| `gemini`       | `gemini-2.0-flash`  | `GEMINI_API_KEY`                       |
| `codex`        | `gpt-4o`            | `OPENAI_API_KEY`                       |

> **`claude` (default)** calls the metered Anthropic API directly — requires
> `ANTHROPIC_API_KEY`, and unlike `claude_code` has no Claude Code CLI/login or
> subscription session-window limit, plus it's the only path with prompt caching.
> **`claude_code`** instead routes AI through your logged-in Claude Code subscription
> via the Agent SDK — no metered API key is used, but `ANTHROPIC_API_KEY` must NOT be
> present in the environment or the SDK/CLI would prefer it and bill metered.

### Hybrid provider tiering (optional — unattended/nightly runs only)
```python
FAST_PROVIDER    = os.environ.get("FAST_PROVIDER", "") or AI_PROVIDER
QUALITY_PROVIDER = os.environ.get("QUALITY_PROVIDER", "") or AI_PROVIDER
```
Both default to `AI_PROVIDER`, so this is a no-op for interactive/local runs — leave it
alone unless you're setting up unattended scheduling. `FAST_PROVIDER` covers stage 1
scoring + stage 3 outreach (many small calls); `QUALITY_PROVIDER` covers stage 2 tailor +
stage 5/6 (few, larger calls). The repo's `.github/workflows/nightly-pipeline.yml` sets
`FAST_PROVIDER=claude` (metered, cheap, prompt-cached) and `QUALITY_PROVIDER=claude_code`
(subscription — free marginal capacity off-hours, when nothing else is using the session
window). For headless subscription auth in CI, run `claude setup-token` locally once
(requires Claude Pro/Max) and store the result as the `CLAUDE_CODE_OAUTH_TOKEN` repo secret.

### API keys
All keys are read from the environment (`os.environ.get(...)`) in `config/settings.py` —
**never hardcode a live key into the file itself**, even locally; set them in your shell
profile, a local `.env` you source yourself, or your CI secrets store.
```
ANTHROPIC_API_KEY = ...   # https://console.anthropic.com        (provider: claude, default)
GEMINI_API_KEY    = ...   # https://aistudio.google.com/apikey   (provider: gemini)
OPENAI_API_KEY    = ...   # https://platform.openai.com/api-keys (provider: codex)
APIFY_API_TOKEN   = ...   # https://apify.com (free token) — LinkedIn + Indeed sourcing
NOTION_API_KEY    = ...   # https://www.notion.so/my-integrations (PRIMARY data store)
HUNTER_API_KEY    = ...   # https://hunter.io (optional — Step 7 spike script only)
```
Set only the AI key matching `AI_PROVIDER` (or `FAST_PROVIDER`/`QUALITY_PROVIDER` if you've
split them). Under `claude_code`, no AI key is needed. `HUNTER_API_KEY` is only consumed by
`scripts/spike_phase0_leads.py` (see `docs/backlog/step-7-communications-subsystem.md`) — the
core pipeline never reads it.

### Notion (primary data store — required)
```python
NOTION_API_KEY = "..."   # the integration token
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
| `Status` | select | pipeline: `Interested`, `Scraped`, `Reviewed`, `Resume Tailored`, `Applied`, `Outreach Sent`, `Interview Scheduled`, `Offer Received`, **`Retry`**<br>manual-only: `Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review` |
| `ATS Match Score` | number | |
| `Date Scraped` | date | |
| `Tailored Resume Link` | url | |
| `Date Applied` | date | |
| `Hiring Manager` | rich_text | |
| `Hiring Manager LinkedIn` | url | |
| `Sponsorship` | select — `yes`/`no`/`unknown` | written by stage 1 scoring |
| `Scoring Attempts` | number | incremented by `rescore_retry_jobs()` each retry pass |
| `Posted Date` | date | multi-source; only written when the source provides one |
| `Source` | rich_text | which registry entry found it (`linkedin`/`indeed`/`greenhouse`/`lever`/`ashby`) |
| `Applicant Count` | number | only written when the source provides one |
| `Salary Range` | rich_text | only written when the source provides one |

> The full **job description is not a property** — it is cached in the page **body**
> (paragraph blocks) by `db_add_job` / `db_add_job_linked` and read back by
> `db_get_job_description()`.

> The last six properties above (`Sponsorship` onward) are each written **only when the job
> dict has that value** — their absence from your DB doesn't break anything, those columns
> just stay empty until you add them. **`Retry` is not auto-created by the Notion API** — a
> write to it will silently drop that property unless you add it to the `Status` select's
> options by hand once, same as any other status.

Create each `Status` select option once (type it into the select to create it), and
make sure the Notion integration is **shared with the database**.

### Retry status (scoring reliability queue)
A job whose AI scoring call fails is written as `Status = Retry` (empty ATS score) instead of
a fabricated score. Every stage 1 run automatically re-scores the `Retry` queue first, from
the already-cached JD (no repeat Apify call) — you don't need to do anything by hand beyond
creating the `Retry` select option once. `python run.py --setup` prints the current queue size.

### Notion intake & review statuses

Two statuses are set by you in Notion, not by the scripts:
- **`Interested`** — add a job by hand (Job Title + Company + Job URL); the next scrape
  ingests, enriches, and scores it (`python run.py --ingest` runs only this).
- **`Reviewed`** — approve a scraped job for tailoring; `python run.py --evaluate` reads
  these straight from Notion and runs stages 2–4.

In the Notion DB's **Status** select, add `Interested` and `Reviewed` as options (type them
once into the select to create them).

---

## 6. (Optional) Unattended nightly runs via GitHub Actions

`.github/workflows/nightly-pipeline.yml` runs the pipeline off-hours on a cron schedule
(default `0 7 * * *` UTC — adjust the hour for your timezone/DST). It uses the hybrid
provider split from step 4 above. Set these as **repo secrets** (Settings → Secrets and
variables → Actions):

| Secret | Required for |
|---|---|
| `NOTION_API_KEY` | always |
| `ANTHROPIC_API_KEY` | `FAST_PROVIDER=claude` (metered, stage 1/3) |
| `CLAUDE_CODE_OAUTH_TOKEN` | `QUALITY_PROVIDER=claude_code` (subscription, stage 2/5/6) — mint with `claude setup-token` locally (Pro/Max required) |

`APIFY_API_TOKEN` isn't in that workflow's `env:` block yet — add it as a secret and wire it
in the same way if you enable `ENABLED_SOURCES` entries that need Apify (`linkedin`,
`indeed`). You can also trigger it manually via `workflow_dispatch` with a `mode` input
(`full`, `scrape`, `evaluate`, `ingest`, or a single `stageN`).

## 7. (Optional) Gmail digest setup

1. Create a Google Cloud project and enable the **Gmail API**.
2. Create OAuth client credentials and download the JSON.
3. Save it to `config/gmail_credentials.json`.
4. Use `--send` on stage 4 to email the digest.

---

## 8. Verify the setup

```bash
python run.py --setup
```

This prints a ✓/✗ checklist for the active provider key(s) (fast + quality tier if split),
Apify token, Notion API key (primary data store), Notion DB ID, resume file, and installed
packages, plus the current `Retry` queue size. Fix any ✗ before running. Output dirs under
`output/` are auto-created on first run.

---

## 9. Run it

```bash
python run.py                                   # Step 1: scrape + review digest (stages 1, 4) — then review in Notion
python run.py --ingest                          # ingest only Notion "Interested" jobs → "Scraped"
python run.py --evaluate                        # Step 2: sync "Reviewed", then tailor + outreach + digest
python run.py --stage 1                          # scrape all ENABLED_SOURCES → store
python run.py --stage 2 --min-score 65           # tailor Reviewed resumes (≥65 ATS only)
python run.py --stage 3 --company "Stripe"       # cold outreach
python run.py --stage 3 --company "Google" --contact "Jane Doe"   # warm referral
python run.py --stage 4 --send                   # digest, emailed via Gmail
python run.py --stage 5 --company "Meta" --role "Senior PM"       # interview prep
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000   # negotiation
```

---

## 10. Outputs

| Path | Contents |
|------|----------|
| `output/resumes/` | Tailored resumes per job — `.docx` (in-place edits of your base resume) + `.txt` mirror |
| `output/outreach/` | Cold + warm email drafts (`.txt`) — reviewed before sending |
| `output/prep_guides/` | Interview prep guides (`.html`) |
| `output/negotiation/` | Negotiation briefs (`.html`) |
| `output/digest_YYYY-MM-DD.html` | Daily digest |

Status pipeline (tracked in Notion, the single source of truth):
`Interested (manual intake) → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received`

`Retry` is a side queue, not a pipeline step — a job lands there only when its AI scoring
call fails, and stage 1 automatically re-scores it on the next run.

Five further options — `Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review` — are set
by hand and written by no stage. A row parked in one of them drops out of the pipeline but is still
seen by dedup, so it will not be re-scraped.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Resume not found` | Add `config/resume.txt` |
| Provider key ✗ | Set `ANTHROPIC_API_KEY` (default provider `claude`), or switch `AI_PROVIDER` to `claude_code` and run `claude /login` instead |
| Notion errors / empty results | Set `NOTION_API_KEY`, share the DB with the integration, and match the schema in step 5 |
| `notion-client` version error | Pin `notion-client>=2.2.1,<2.6` (2.6+/3.x dropped `databases.query`) |
| Apify timeouts | Scraper retries 30×10s; retry on network errors |
| Gmail send fails | Ensure `config/gmail_credentials.json` exists (OAuth) |
| Duplicate jobs | Dedup is by job URL **and** by company+title fingerprint (`job_fingerprint()`); check the `Job URL` property for trailing slashes / query params |
| A Lever/Ashby board resolves to the wrong company | Check `config/ats_tokens.json` — auto-accepted tokens are logged loudly on discovery; delete/fix the bad entry by hand |
| Jobs stuck in `Retry` past `MAX_SCORING_ATTEMPTS` | They're promoted to `Scraped` with an empty score rather than retried forever — score them manually or re-run once the underlying AI error is fixed |
