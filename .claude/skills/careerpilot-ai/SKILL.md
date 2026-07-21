---
name: careerpilot-ai
description: Single entry point to run, test, or drive the careerpilot-ai AI job search pipeline. Use for any stage (scrape/tailor/outreach/digest/interview/negotiate/apply), setup, status check, or smoke test. Trigger with an action argument, e.g. /careerpilot-ai scrape.
trigger: /careerpilot-ai
---

# careerpilot-ai

Python CLI pipeline, single entry point (`run.py`; deterministic — Claude is called as a
subroutine for scoring/tailoring only). No GUI, no server.

This skill is invoked as `/careerpilot-ai <action> [flags]`. `<action>` selects which section
below applies; `[flags]` pass straight through to the underlying `python run.py ...` call.
Running with no action shows this action table plus the Prerequisites section.

| Action | Runs | What it does |
|---|---|---|
| *(none)* | — | Show this table + Prerequisites |
| `setup` | `run.py --setup` | Verify config/keys/deps |
| `setup-profile` | `run.py --setup-profile` | One-time Stage 7 answer wizard |
| `smoke-test` | `smoke.py` | Agent-safe CLI smoke test, no API keys needed |
| `morning` | `run.py` | Full daily flow: scrape + review digest (stages 1, 4) |
| `scrape` | `run.py --stage 1` | Scrape + score + ingest "Interested" |
| `tailor` | `run.py --stage 2` | Tailor resumes for "Reviewed" jobs |
| `outreach` | `run.py --stage 3` | Draft cold/warm outreach |
| `digest` | `run.py --stage 4` | Morning ready-to-apply digest |
| `interview` | `run.py --stage 5` | Interview prep guide |
| `negotiate` | `run.py --stage 6` | Salary negotiation brief |
| `apply` | `run.py --stage 7` | Auto-apply prep (plan + answer sheet; `--fill` to pre-fill browser; never submits) |
| `status` | *(freeform)* | Read Notion/config/output state, recommend next action |

---

## Prerequisites

Python 3.9+ with these packages (already installed if `setup` passed):

```bash
pip install -r requirements.txt        # or: anthropic notion-client requests python-docx
```

API keys, all read from the environment in `config/settings.py` (`os.environ.get(...)` — never a
literal in the file):
- Provider auth matching `AI_PROVIDER` (or `FAST_PROVIDER`/`QUALITY_PROVIDER` if split) —
  `ANTHROPIC_API_KEY` (default, `"claude"`, metered API), or Claude Code subscription
  (`claude_code`; run `claude /login`), `OPENAI_API_KEY` (codex), `GEMINI_API_KEY` (gemini).
- `APIFY_API_TOKEN` — LinkedIn + Indeed scraping via Apify (apify.com, free tier works); not
  needed if `ENABLED_SOURCES` only has `greenhouse`/`lever`/`ashby`
- `NOTION_API_KEY` — Notion integration key (notion.so/my-integrations); **primary data store**
  (the DB must be shared with the integration)
- `HUNTER_API_KEY` — optional, only used by `scripts/spike_phase0_leads.py` (Step 7 spike), not
  the core pipeline

Resume at `config/resume.txt` (plain text) and the base `config/Achyuth_Resume.docx` for
stage-2 in-place tailoring.

---

## `setup`

```bash
python run.py --setup
```

Checks API keys, resume file, Python packages (including a split `FAST_PROVIDER`/`QUALITY_PROVIDER`),
and the current `Retry` queue size. Reports exactly which items are missing.

**First-time checklist:**
1. Edit `config/settings.py` — fill in `YOUR_NAME`, `YOUR_EMAIL`, `YOUR_BIO`, `TARGET_ROLES`,
   `TARGET_COMPANIES`, `ENABLED_SOURCES`
2. Set API keys as env vars: `ANTHROPIC_API_KEY`, `APIFY_API_TOKEN`, `NOTION_API_KEY`
   (`HUNTER_API_KEY` optional, Step 7 spike only)
3. Add your resume text to `config/resume.txt`
4. Add the `Retry` status option to the Notion DB's `Status` select by hand once (the API can't
   create it)
5. **Before the first real (non-dry) `apply` run:** run
   `python scripts/setup_notion_schema.py --apply` once — idempotent, adds the six new `Status`
   options and four new properties Stage 7 needs. Skipping it isn't silent:
   `db_update_status_verified()` fails loudly on the first write instead of corrupting the tracker.
6. **Before your first `apply` run:** run `setup-profile` (below) to capture your application
   answers
7. Run `setup` to verify
8. Run `scrape` to start the pipeline

**Install dependencies:**
```bash
pip install -r requirements.txt
```

## `setup-profile`

```bash
python run.py --setup-profile          # capture your Stage 7 application answers
python run.py --setup-profile --show   # print saved answers, change nothing
```

Interactive one-time wizard that writes your work-authorization/sponsorship/notice-period/etc.
answers to the git-ignored `config/application_profile.json`, which `config/settings.py` overlays
over the `APPLICATION_PROFILE`/`EEO_RESPONSES`/`COMMON_QUESTION_PRESETS` defaults. Prompts pre-fill
from the current effective value; pressing Enter through the whole thing changes nothing. `clear`
un-sets an eligibility answer back to "always ask me" (sponsorship/work-auth answers are never
guessed and are always reversible this way).

---

## Smoke test (`smoke-test`)

```bash
python .claude/skills/careerpilot-ai/smoke.py
```

Agent-safe path — no API keys needed. Tests: CLI parses correctly, `--setup` runs, bad stage
exits 1, all 7 stage modules import. Output on a clean machine (keys not set):

```
Smoke test — careerpilot-ai

  PASS  run.py --help
  PASS  run.py --setup (runs without crash)
  PASS  run.py --stage 99 exits 1
  PASS  all stage modules import cleanly

  PASS  All smoke tests passed
```

---

## Rule of thumb: every change ships with a test

Before treating any code change as done — whether you made it directly or via a subagent:

1. **Logic change** (`scripts/*.py`, `run.py`): add or update a pytest test under `tests/`,
   reusing `tests/conftest.py`'s `patch_ai_chat`/`patch_notion_db` fakes rather than hitting a
   real AI/Notion call. Then run:
   ```bash
   pytest -v
   ```
   Mocked, no API keys/Notion/Claude Code login needed, ~1.5s for the default suite (browser
   tests behind `pytest -m browser` are excluded by default). Must be green.
2. **Prompt or model change** (stage 1 scoring, stage 2 tailoring, stage 3 outreach,
   `QUALITY_MODEL`/`AI_MODEL_OVERRIDE`): pytest alone can't catch judgment drift since it replays
   mocked/recorded responses. Also run the real-API eval layer:
   ```bash
   python scripts/run_evals.py            # stage 1 scoring + keyword recall
   python scripts/run_evals.py --tailor   # + stage 2 tailoring ATS delta
   ```
   Costs real tokens (never run by CI) — check score-hit-rate / keyword recall / ATS delta
   against `tests/eval_data/jobs.json` for a regression before and after the change.

Don't report a change complete without at least step 1.

---

## `morning`

```bash
python run.py $ARGUMENTS
```

Full daily flow (stages 1, 4): scrape every enabled source → score against your resume (ATS
match %) → generate an HTML review digest of "Scraped" jobs, then stop.

Check `output/review_digest_{date}.html` when complete. Mark good jobs `Status = Reviewed` in
Notion, then run `python run.py --evaluate` (tailor → outreach drafts → ready digest).

## `scrape`

```bash
python run.py --stage 1 $ARGUMENTS
```

- Re-scores any jobs stuck in `Status="Retry"` from a previous failed scoring pass first (cached
  JD, no repeat Apify call)
- Ingests any Notion `Status="Interested"` rows (manual intake) — same as `--ingest`
- Gathers listings from every `ENABLED_SOURCES` entry (`config/settings.py`): `linkedin`/`indeed`
  (Apify, per `TARGET_ROLES`), `greenhouse`/`lever`/`ashby` (free keyless board APIs, per
  `TARGET_COMPANIES`)
- Deduplicates via Job URL **and** company+title fingerprint (catches the same job posted to
  multiple sources — keeps the ATS-board copy over LinkedIn/Indeed)
- Filters by freshness (`MAX_JOB_AGE_DAYS`), company/title denylist, sponsorship, `MIN_ATS_SCORE`
- Scores each survivor against your resume via Claude (0–100 ATS match, sponsorship, company_type)
  in one batched call; a failed scoring call writes `Status="Retry"` instead of a fabricated score
- Saves new jobs to Notion with `Status="Scraped"` (or straight to `"Reviewed"` if confident —
  see `_auto_review_status()` in `CLAUDE.md`)

Check Notion tracker after completion. Jobs need `Status="Scraped"` before `tailor` can run.

## `tailor`

```bash
python run.py --stage 2 $ARGUMENTS
```

Common usage:
- `tailor` — tailor all "Reviewed" jobs (no score filter)
- `tailor --min-score 65` — only jobs with ATS ≥ 65 (only filter Stage 2 supports; no per-company)

- Fetches all Notion jobs with `Status="Reviewed"` (filtered by `--min-score` if set)
- Fetches the actual job description via HTTP (real fetch, not Claude browsing)
- Rewrites your resume to match each JD via targeted `{old→new}` keyword edits applied in-place
  to the base `.docx`, preserving formatting
- Saves tailored resume as `.docx` + `.txt` to `output/resumes/`
- Updates Notion: `Status → "Resume Tailored"`

Check `output/resumes/` for generated files. Review before applying.

## `outreach`

```bash
python run.py --stage 3 $ARGUMENTS
```

Common usage:
- `outreach --company "Stripe"` — cold email for Stripe
- `outreach --company "Google" --contact "Jane Doe" --contact-role "PM"` — warm LinkedIn message

- Fetches "Resume Tailored" jobs from Notion (filtered by `--company` if set)
- Warm referral (`--contact` provided): 3-sentence LinkedIn DM, friendly + specific
- Cold email (no contact): short email under 100 words with subject line (JSON)
- Saves drafts to `output/outreach/` — **not** auto-sent (review first)

**Manual review gate (canonical explanation — other docs point here):** running stage 3 directly
prompts with `input()` before writing "Outreach Sent" status, by design, so emails are reviewed
and personalized before sending. This blocks in a non-interactive context — pipe a newline:
`echo "" | python run.py --stage 3 --company "Stripe"`. `python run.py --evaluate` runs stage 3
with `no_confirm=True`, so it does **not** prompt — drafts are saved but status is not
auto-advanced (you mark it after reviewing).

## `digest`

```bash
python run.py --stage 4 $ARGUMENTS
```

Common usage:
- `digest` — generate HTML digest, print to terminal
- `digest --send` — also send via Gmail (requires `config/gmail_credentials.json` OAuth setup)

- Fetches all Notion jobs with `Status="Resume Tailored"` and no Date Applied
- Sorts by ATS match score (highest first); action suggestion per tier: ≥80 apply directly today,
  ≥60 apply + warm outreach, ≥40 apply + consider adjacent angle, <40 apply to adjacent roles first
- Saves HTML to `output/digest_{date}.html`; optionally emails via Gmail

## `interview`

```bash
python run.py --stage 5 $ARGUMENTS
```

Required: `--company "CompanyName" --role "Role Title"` (optional `--jd-file`).

Example: `interview --company "Meta" --role "Senior PM"`

Uses Claude to research the company/role/likely interview format and generates an HTML prep
guide (company background, role competencies, behavioral questions in STAR format, technical/case
questions, questions to ask the interviewer). Saves to
`output/prep_guides/{company}_{role}_prep.html`. Review 24–48 hours before your interview.

## `negotiate`

```bash
python run.py --stage 6 $ARGUMENTS
```

Required: `--company "CompanyName" --role "Role Title" --offer AMOUNT`

Example: `negotiate --company "Stripe" --role "PM" --offer 185000`

Researches salary benchmarks (Levels.fyi/Glassdoor-style ranges), analyzes your offer vs. market,
and generates an HTML negotiation guide: market rate analysis, counter-offer recommendation,
word-for-word script, written counter-offer email template, common pushbacks + responses. Saves
to `output/prep_guides/{company}_{role}_negotiate.html`.

## `apply`

```bash
python run.py --stage 7                        # plan + answer sheets (never submits)
python run.py --stage 7 --dry-run --limit 3     # sample: real sheets, no Notion writes, first 3
python run.py --stage 7 --fill                  # also pre-fill the form in a browser
```

Picks up jobs at `Resume Tailored` and prepares the application: routes by ATS (Greenhouse/Lever
fillable; LinkedIn/Indeed answer-sheet-only by rule, never filled — ToS + bot detection),
resolves each field to `ready`/`review_required` from `APPLICATION_PROFILE`/`EEO_RESPONSES`
/`COMMON_QUESTION_PRESETS` (facts only — AI never guesses eligibility/sponsorship/salary answers),
and writes an HTML answer sheet to `output/applications/`. **Never submits and never sets
`Status=Applied`** — a human clicks Submit and marks it by hand.

Prerequisite: run `python scripts/setup_notion_schema.py --apply` once (see `setup` checklist)
before the first real (non-dry) run, and `setup-profile` to capture your answers.

## `status`

Not a `run.py` wrapper — a read-only check-and-report task. When invoked:
1. **Config check** — read `config/settings.py` for `NOTION_DB_ID`; confirm required API keys are
   set and `config/resume.txt` is populated.
2. **Output files** — list recent files in `output/resumes/`, `output/outreach/`,
   `output/prep_guides/`, `output/applications/` with dates.
3. **Retry / Human Review queues** — count Notion rows at `Status="Retry"` (failed AI scoring,
   awaiting the next `scrape`) and `Status="Human Review"` (sponsorship gate hits).
4. **Next recommended action** — based on what's present, suggest which action above to run next.

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
| 7 (apply) | `output/applications/` answer sheets + fill screenshots (never submits) |

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

- **Stage 3 `input()` gate** — see the `outreach` section above for the canonical explanation and
  the non-interactive workaround.
- **Apify scraper waits 30×10s** — the LinkedIn scrape polls up to 5 minutes. Don't kill early;
  the run ID is lost and you'd need to restart `scrape`.
- **`config/resume.txt` must be non-empty** — `setup` checks existence but not content. A 0-byte
  file passes the check but fails at runtime when the resume is injected into the prompt.
- **Windows encoding** — both CLIs call `sys.stdout.reconfigure(encoding="utf-8")` at startup. If
  you see `UnicodeEncodeError` in a shell that doesn't support UTF-8, run with
  `PYTHONIOENCODING=utf-8`.
- **Stage 7 never submits** — there is no submit code path at all in `scripts/autoapply_browser.py`
  (not behind a flag). A human always clicks Submit and sets `Status=Applied` by hand.

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
| `apply` job stuck, status never advances past `Application Queued`/`Applying`, or a new Stage 7 `Status` option never sticks | Run `python scripts/setup_notion_schema.py --apply` — the six new Stage 7 `Status` options and four new properties must exist before `db_update_status_verified()` can write them; it fails loudly rather than silently no-opping |
