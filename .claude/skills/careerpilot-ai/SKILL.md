---
name: careerpilot-ai
description: Run, test, or drive the careerpilot-ai AI job search pipeline. Use when asked to run the pipeline, start a stage, smoke test, check setup, or verify the CLI works.
trigger: /careerpilot-ai
---

# careerpilot-ai

Python CLI pipeline, single entry point. Driven via smoke script for agent testing; no GUI, no server.

- **`run.py`** — direct stage runner (deterministic; Claude is called as a subroutine for scoring/tailoring only)

Driver: `.claude/skills/careerpilot-ai/smoke.py`

---

## Prerequisites

Python 3.9+ with these packages (already installed if setup passed):

```
pip install -r requirements.txt        # or: anthropic notion-client requests docxtpl
```

API keys, all read from the environment in `config/settings.py` (`os.environ.get(...)` — never a literal in the file):
- Provider auth matching `AI_PROVIDER` (or `FAST_PROVIDER`/`QUALITY_PROVIDER` if split) — `ANTHROPIC_API_KEY` (default, `"claude"`, metered API), or Claude Code subscription (`claude_code`; run `claude /login`), `OPENAI_API_KEY` (codex), `GEMINI_API_KEY` (gemini).
- `APIFY_API_TOKEN` — LinkedIn + Indeed scraping via Apify (apify.com, free tier works); not needed if `ENABLED_SOURCES` only has `greenhouse`/`lever`/`ashby`
- `NOTION_API_KEY` — Notion integration key (notion.so/my-integrations); **primary data store** (the DB must be shared with the integration)
- `HUNTER_API_KEY` — optional, only used by `scripts/spike_phase0_leads.py` (Step 7 spike), not the core pipeline

Resume at `config/resume.txt` (plain text) and the base `config/Achyuth_Resume.docx` for stage-2 in-place tailoring.

---

## Smoke test (agent path — no API keys needed)

```
python .claude/skills/careerpilot-ai/smoke.py
```

Tests: CLI parses correctly, `--setup` runs, bad stage exits 1, all 7 modules import. Output on a clean machine (keys not set):

```
Smoke test — careerpilot-ai

  PASS  run.py --help
  PASS  run.py --setup (runs without crash)
  PASS  run.py --stage 99 exits 1
  PASS  all stage modules import cleanly

  PASS  All smoke tests passed
```

---

## Setup check

```
python run.py --setup
```

Checks API keys, resume file, Python packages. Reports exactly which items are missing.

---

## Run: run.py

Direct Python calls to each stage script:

```bash
python run.py --setup
python run.py                               # Step 1: scrape + review digest (stages 1, 4) — STOP for review
python run.py --ingest                      # ingest only Notion "Interested" jobs → "Scraped"
python run.py --evaluate                    # Step 2: sync "Reviewed" from Notion → tailor + outreach + digest
python run.py --stage 1                     # scrape only (also ingests "Interested")
python run.py --stage 2 --min-score 65
python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
python run.py --stage 4 --send
python run.py --stage 5 --company "Meta" --role "Senior PM"
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000
```

**Two-step flow:** `python run.py` scrapes and stops at a review digest. You mark good jobs
`Status = Reviewed` in Notion, then `python run.py --evaluate` tailors them. Jobs you add by
hand in Notion with `Status = Interested` are pulled in on the next scrape (or `--ingest`).

---

## Output locations

| Stage | Output |
|---|---|
| 1 (scrape) | Notion rows, status=Scraped (incl. ingested "Interested") |
| 2 (tailor) | `output/resumes/{date}_{company}_{role}.docx` + `.txt`, status=Resume Tailored |
| 3 (outreach) | `output/outreach/{date}_{company}_outreach.txt` (not auto-sent) |
| 4 (digest) | `output/digest_{date}.html` / `review_digest_{date}.html`, optional Gmail send |
| 5 (interview) | `output/prep_guides/{company}_{role}_prep.html` |
| 6 (negotiate) | `output/prep_guides/{company}_{role}_negotiate.html` |

---

## Status pipeline (Notion — single source of truth)

```
Interested (manual) → Scraped → Reviewed → Resume Tailored → Applied → Outreach Sent → Interview Scheduled → Offer Received
```

Five off-pipeline options — `Disregard`, `Blacklist`, `Archived`, `Rejected`, `Human Review` —
are set by hand; no stage writes them. Parked rows drop out of the pipeline but still count as
duplicates on the next scrape.

Status names are case-sensitive. Each stage reads the previous status and writes the next.
`Interested` and `Reviewed` are set by the user in Notion: `Interested` queues a hand-added
job (ingested on the next scrape); `Reviewed` approves a scraped job for `--evaluate`.

---

## Gotchas

- **Stage 3 `input()` gate (direct `--stage 3` only)** — running stage 3 directly prompts before writing outreach status (manual review by design). In a non-interactive context this blocks — pipe a newline: `echo "" | python run.py --stage 3 --company "X"`. Note: `python run.py --evaluate` runs stage 3 with `no_confirm=True`, so it does **not** prompt.
- **Apify scraper waits 30×10s** — the LinkedIn scrape polls up to 5 minutes. Don't kill early; the run ID is lost and you'd need to restart stage 1.
- **`config/resume.txt` must be non-empty** — `--setup` checks existence but not content. A 0-byte file passes the check but fails at runtime when the resume is injected into the prompt.
- **Windows encoding** — both CLIs call `sys.stdout.reconfigure(encoding="utf-8")` at startup. If you see `UnicodeEncodeError` in a shell that doesn't support UTF-8, run with `PYTHONIOENCODING=utf-8`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: anthropic` | `pip install anthropic` |
| `✗ Resume file` in setup | Create `config/resume.txt` with your resume text |
| `Apify run FAILED` | Check `APIFY_API_TOKEN`; Apify free tier has rate limits — wait 10 min and retry |
| `notion_client.errors.APIResponseError` | Check `NOTION_API_KEY` and that the integration is shared with the database |
| Stage 3 hangs | Waiting for `input()` — see Gotchas above |
| `[Errno 2] No such file or directory: 'output/...'` | Dirs are auto-created on first run; check you're running from the project root |
