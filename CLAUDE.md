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
| 7 | `scripts/autoapply.py` (+ `scripts/autoapply_browser.py`) | Auto-apply prep: plan every application answer, emit an answer sheet, optionally pre-fill the form in a browser. **Never submits** |

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

### Restricted-sponsorship company list (Notion-managed, Step 12)

Companies known (from your own research/contacts) to sponsor only *existing* employees, not
new external hires, are tracked in their own small Notion **database** — parallel to the Jobs
Tracker and the Scratch Pad — rather than a hardcoded list, so you can add/remove a company
visually with no code change or redeploy (this also matters once the pipeline runs from
GitHub Actions, where a git-ignored local file wouldn't exist). `python run.py --init` (→
`scripts/provision_notion.py`) provisions this database automatically alongside the Jobs
Tracker and Scratch Pad, under the same "Careerpilot-ai" page, and writes its id to `.env` —
or create it by hand: one small database (e.g. titled "Restricted Sponsorship Companies")
where each row's title is one company name, shared with the same integration used for
`NOTION_API_KEY`, with its database id set as `NOTION_RESTRICTED_COMPANIES_PAGE_ID` (optional;
the feature no-ops if unset).
`get_restricted_sponsorship_companies()` (`scripts/utils.py`) merges this Notion list with the
hardcoded `RESTRICTED_SPONSORSHIP_COMPANIES` fallback/escape-hatch in `config/settings.py`
(for when Notion is unreachable, or before the database exists) — the single call site both
enforcement points below use. **Stage 1** (`is_restricted_sponsorship_company()` in
`scripts/stage1_scrape.py`) drops a matching company silently at scrape time, the same as
`SKIP_COMPANIES`, logged under the `restricted-sponsorship` drop counter — it never reaches
the Jobs DB at all. **Stage 2**'s `_sponsorship_gate()` (see "Stage 2 Sponsorship Gate" below)
checks the same merged list as defense-in-depth, for a job that reached `Reviewed` *before*
its company was added to the list.

### Shared utilities (`scripts/utils.py`)

- `ai_chat(prompt, system, max_tokens, quality)` — provider-agnostic chat; `claude_chat` is an alias
- `ai_chat_blocks(blocks, ...)` — Claude-only structured content blocks with `cache_control`
- `db_find_job_by_url()` — one-off URL lookup. Returns the page id, or `None` for a genuine miss; **raises `RuntimeError` on a failed read** rather than returning `None`, since `None` means "no such job" and callers act on it by creating a row
- `db_add_job()`, `db_update_status()`, `db_get_jobs()`, `db_get_all_jobs()`, `db_get_ready_to_apply()`, `db_get_job_by_company()`, `db_get_job_description()` — Notion-backed CRUD (`page_id`/`id` is the Notion page id; the JD is cached in the page body via paragraph blocks)
- `db_get_all_jobs()` — one unfiltered paginated read of every row (`page_id, title, company, location, url, status, ats_score`); backs Stage 1's in-memory dedup (URL set + fingerprint set). **Raises `RuntimeError` on a failed read** — Stage 1 aborts the scrape rather than treating a failed read as an empty DB (which would mass-duplicate the tracker)
- `db_update_status_verified(job_id, status, extra_props)` — like `db_update_status()`, but re-reads the page and returns `False` (loudly logged) if Notion silently ignored the status. Used by stage 7, whose statuses are new select options a user may not have added yet; a silent no-op there would leave the job to be re-processed every run
- `db_add_job_linked(job, notion_page_id)` — promote an existing manually-added Notion page ("Interested" intake) to "Scraped" in place (no duplicate page); caches the JD in its body
- `get_notion_jobs_by_status(status)` — read Notion rows by status (paginated, via `_query_db()` like every other reader). **Raises `RuntimeError` on a failed read**, same contract as `db_get_all_jobs()` — a failed read must never be reported as "no rows with this status", since callers act on emptiness by creating rows. `sync_notion_to_supabase()` is now a no-op kept for compatibility (Notion is the store)
- `get_scratch_note_entries()` / `archive_scratch_note_entry(page_id)` / `db_add_interested_url(url)` — the scratch-note read/archive/create helpers backing `ingest_from_scratch_note()` above (see "Scratch-note intake")
- `get_restricted_companies_from_notion()` / `get_restricted_sponsorship_companies()` — the Notion read and hardcoded-fallback merge backing the restricted-sponsorship company list (see "Restricted-sponsorship company list" above)
- `load_resume()`, `ensure_dirs()`, `today()`, `parse_json_response()` — misc helpers

**Configuration:** `config/settings.py` — all API keys, user profile, target roles, AI model settings, output paths.

## Common Commands

```bash
python run.py                                                    # Scrape + review digest (stages 1, 4) — STOP for review
python run.py --ingest                                          # Promote scratch-note URL drops, then ingest Notion "Interested" jobs → Scraped
python run.py --evaluate                                        # Sync "Reviewed" from Notion, then tailor + outreach + digest
python run.py --init                                             # One-time fork onboarding: Notion details → provision page + DBs → write ids to .env
python run.py --setup                                            # Verify config (+ validate the live Notion schema)
python run.py --stage 1                                          # Scrape only (also ingests "Interested")
python run.py --stage 2 --min-score 65
python run.py --stage 3 --company "Stripe" --contact "Jane Doe"
python run.py --stage 4 --send
python run.py --stage 5 --company "Meta" --role "Senior PM"
python run.py --stage 6 --company "Stripe" --role "PM" --offer 185000
python run.py --stage 7                                          # Auto-apply prep (never submits)
python run.py --stage 7 --fill                                   # ...and pre-fill the form in a browser
python run.py --ai-mode {metered,hybrid,subscription} --metered-provider {claude,codex,gemini,openrouter}  # Per-run override
```

The `careerpilot-ai` Claude Code skill (`.claude/skills/careerpilot-ai/SKILL.md`) wraps these as
`/careerpilot-ai <action>` (e.g. `/careerpilot-ai scrape`, `/careerpilot-ai apply`) — per-stage
slash commands (`/scrape`, `/tailor`, ...) were consolidated into this one skill; use its action
table for the full mapping.

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
- `get_restricted_sponsorship_companies()` (Notion list + `RESTRICTED_SPONSORSHIP_COMPANIES`
  fallback) — word-boundary denylist for companies known to sponsor only existing employees,
  not new hires; see "Restricted-sponsorship company list" above
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

The restricted-sponsorship company list (see "Restricted-sponsorship company list" above —
the Notion database at `NOTION_RESTRICTED_COMPANIES_PAGE_ID`, merged with the hardcoded
`RESTRICTED_SPONSORSHIP_COMPANIES` fallback in `config/settings.py`) names companies known
(from your own research/contacts) to sponsor only **existing** employees, not new external
hires — even when the JD reads as sponsorship-friendly or says nothing. **Stage 1 is the
primary enforcement point**: it drops a matching company silently at scrape time, like
`SKIP_COMPANIES`, so these jobs are never scraped, scored, or tracked. Stage 2
(`_sponsorship_gate()`) checks the same merged list as **defense-in-depth**, for the case
where a job reached `Reviewed` *before* its company was added to the list: it holds back that
`Reviewed` job by moving its Notion Status to `Human Review` and writing a guidance note,
without tailoring a resume. To release a held job, confirm sponsorship for a new hire
yourself, add `SPONSORSHIP_CONFIRMED_MARKER` (default: `"sponsorship confirmed"`) to that
job's Notion **Notes** field, then move its Status back to `Reviewed` by hand — stage 2
checks for the marker before re-gating it.

## Stage 7 Auto-Apply (Step 10, Phases 1–2)

Picks up jobs at `Resume Tailored` and prepares the application. **It never submits** — the
human clicks Submit and then sets `Applied` by hand. Two deliberately decoupled layers:

- **Layer 1 — planning (`scripts/autoapply.py`, no browser).** `detect_apply_channel()` routes
  by URL domain (greenhouse/lever/ashby/workday/linkedin/indeed/unknown, matched on a real
  domain boundary so `evilgreenhouse.io` doesn't route as Greenhouse). For Greenhouse it fetches
  the public `?questions=true` field schema — the only public apply-side data any mainstream ATS
  exposes; every other channel falls back to `GENERIC_QUESTIONS` with `schema_known=False`, which
  hedges the readiness verdict since the real form will likely ask more. `build_application_plan()`
  resolves each field to `ready`/`review_required`; `readiness_report()` gates on unresolved
  *required* fields (the only guard — Greenhouse does not validate required fields server-side).
  Writes Notion + an HTML answer sheet to `APPLICATIONS_DIR`. `resolve_tailored_resume()` turns
  the job's `Tailored Resume Link` back into a real local file: a `file://` link (local stage 2
  run) round-trips directly, while a `raw.githubusercontent.com` link (CI-tailored, see "Nightly
  run output" above) is downloaded into `RESUMES_DIR` on the fly — either way a download/lookup
  failure returns `""`, same as a missing local file, so the upload field falls back to
  `review_required` rather than silently attaching nothing.
- **Layer 2 — fill (`scripts/autoapply_browser.py`, Playwright).** Opens the live form, fills
  only `ready` fields, attaches the tailored `.docx`, screenshots, stops. Guarded import and a
  never-raises contract mirroring `_headless_fetch()` in `sources.py`, so Layer 1 keeps working
  when the browser layer can't. **There is no submit code path in that module at all** — not
  behind a flag — and `tests/test_autoapply_notion.py` asserts it stays that way.

**Why no API:** there is no candidate-usable submit endpoint. Greenhouse's
`POST /v1/boards/{token}/jobs/{id}` authenticates as the *employer* (Basic Auth, the company's
board key) and their docs warn a direct post "would reveal your secret key to anybody that views
source". Lever/Ashby are the same. Applying is a browser problem, not an API problem.

**Answer sources (governing rule — enforced in `_resolve_field()`, not by prompt wording):**
`APPLICATION_PROFILE` supplies facts; AI only ever drafts prose. Work authorization, sponsorship,
salary and any yes/no eligibility answer come from the profile or the field is flagged
`review_required` — **never guessed**, since a wrong answer there is disqualifying and
unretractable. `None` means unknown and always blocks; `False` is a real answer and does not.
`EEO_RESPONSES` answers demographic questions (default: decline). `COMMON_QUESTION_PRESETS` is a
label-substring answer bank for recurring screeners; a preset left blank routes to human review
rather than typing an empty answer into a real application.

`_resolve_field()` in `scripts/autoapply.py` resolves fields in order: (a) file uploads → the
stage 2 tailored resume, (b) direct name map (first/last/email/phone, `_FIELD_MAP`), (c) label
rules (`_LABEL_RULES` — eligibility knockouts, EEO, links, and the structured-address fields
below), (d) `COMMON_QUESTION_PRESETS`, (e) free-text → always `review_required`, (f) anything
else → `review_required`. `_LABEL_RULES` is matched on **label text**, not field `name` — beyond
the confirmed-stable `first`/`last`/`email`/`phone` names in `_FIELD_MAP`, Greenhouse's other
field `name` attributes are opaque/internal, so mapping must go by the human-readable question
text instead.

**Structured address section (`APPLICATION_ADDRESS`, `config/settings.py`).** Some Greenhouse
forms ask a full address questionnaire (legal first/last name, address line 1/2, city, state,
country, zip/postal code, address type) as separate fields under their own labels, distinct from
the display name used on the resume/outreach. `run.py --setup-profile` (`scripts/autoapply_profile.py`)
captures these in their own wizard section and persists them to `config/application_profile.json`
alongside the rest of the profile; `config/settings.py` exposes the overlay as
`APPLICATION_ADDRESS`, merged with `APPLICATION_PROFILE` when `build_application_plan()` resolves
a schema (`{**APPLICATION_PROFILE, **APPLICATION_ADDRESS}`). `_LABEL_RULES` maps each field by its
exact label text (e.g. `"legal first name"`, `"address line 1"`, `"zip code"`/`"zip/postal"`/
`"postal code"`) — labels confirmed from a live Greenhouse fetch, not guessed.

**Attachment/textarea dedupe.** Greenhouse emits two field rows under one logical attachment
question: an `input_file` (or `attachment`) field plus a sibling `textarea` for pasting the resume
text instead of uploading it. `build_application_plan()` detects this pairing per question (a
`textarea` alongside an already-present `input_file`/`attachment` field under the same label,
checked order-independently) and mirrors the attachment field's resolution onto the textarea
instead of treating it as an unresolved free-text question — otherwise a fully-answered upload
question would still block on its own redundant textarea sibling.

**Never `Applied`.** `WRITABLE_STATUSES` excludes it on purpose. Comparable open-source
auto-appliers are widely reported to mark jobs applied that were never submitted (captcha stalls,
silent form errors), which corrupts the tracker in the unrecoverable direction — you stop
re-applying to jobs you never actually applied to. This stage doesn't submit, so it must not
claim success.

**LinkedIn/Indeed are never filled.** `FILLABLE_CHANNELS` is `{greenhouse, lever}` by rule, not
configuration: automated applying there violates ToS and is behaviorally detected. They get an
answer sheet only.

**Failure modes handled:** every browser wait is bounded (Turnstile-class challenges are usually
invisible and *stall* rather than error, so a timeout is classified as a probable captcha and
handed off, never retried); a fill resolving under `MIN_RESOLVE_RATIO` of planned fields aborts
as `drift` rather than leaving a half-filled form the human would trust; a PDF-only upload first
tries `render_docx.convert_docx_to_pdf()` (headless LibreOffice — stage 2 only produces `.docx`
directly) and only stops as `pdf_only` if LibreOffice isn't installed or the conversion fails.

`AUTOAPPLY_DAILY_CAP` (default 10) caps applications per run. That's a *quality* guard, not just
politeness — ATSes score application velocity and flag high-volume submitters as low-intent
before a human reads the application.

**One-time setup (`run.py --setup-profile`).** Stage 7's answers come from `APPLICATION_PROFILE`
/ `APPLICATION_ADDRESS` / `EEO_RESPONSES` / `COMMON_QUESTION_PRESETS` in `config/settings.py`, but
editing a checked-in Python file to change your notice period — and committing personal details —
is the wrong ergonomics. `scripts/autoapply_profile.py` (`run.py --setup-profile`) is an
interactive wizard that writes your answers to a **git-ignored** `config/application_profile.json`,
which `settings.py`'s `_apply_saved_profile()` overlays over the defaults at import (a missing or
corrupt file is a no-op, so the defaults stand). Prompts pre-fill from the *effective* current
value, so pressing Enter through the whole thing changes nothing; `clear` un-sets an eligibility
answer back to "always ask me" (so a wrong sponsorship/work-auth answer is reversible — those two
are never guessed). `--show` prints the saved answers without changing anything. Secrets stay
env-sourced as before; this file only holds application answers.

**Sampling before you trust it (`--dry-run` / `--limit`).** `--stage 7 --dry-run` builds real
plans and writes real HTML answer sheets to `APPLICATIONS_DIR` but makes **zero Notion writes**,
so a run is repeatable; `--limit N` overrides `AUTOAPPLY_DAILY_CAP` for a run to sample just a
few. `--dry-run --fill` still never opens a browser. Use these to eyeball the output on real jobs
before committing to the live path.

```bash
python run.py --setup-profile                 # one-time: capture your application answers (git-ignored)
python run.py --setup-profile --show          # print saved answers, change nothing (via autoapply_profile.py)
python run.py --stage 7                        # plan + answer sheets
python run.py --stage 7 --dry-run --limit 3    # sample: real sheets, no Notion writes, first 3 jobs
python run.py --stage 7 --fill                 # also pre-fill in a browser (stops before submit)
python scripts/autoapply.py --sample           # offline plan against the bundled schema
python scripts/autoapply.py --url <greenhouse job>   # live schema fetch
```

Before the first real (non-dry) run, add the new Notion schema once:
`python scripts/setup_notion_schema.py --apply` (idempotent, dry-run by default) creates the six
new `Status` options and four new properties Stage 7 writes. Skipping it isn't silent —
`db_update_status_verified()` fails loudly on the first write rather than corrupting the tracker.

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
- **Notion database schema:** a fork provisions this whole schema automatically with `python run.py --init` (→ `scripts/provision_notion.py`, which owns the canonical `TRACKER_PROPERTIES` / `STATUS_OPTIONS` and creates the "Careerpilot-ai" page + Job Search Tracker + Job Link Scratch Pad + Restricted Sponsorship Companies databases under a shared parent page). The manual reference below is what that creates. The tracker DB (`NOTION_DB_ID`) must have these properties: `Job Title` (title), `Company` (rich_text), `Location` (rich_text), `Job URL` (url), `Status` (select — 14 options: Interested, Scraped, Reviewed, Resume Tailored, Applied, Outreach Sent, Interview Scheduled, Offer Received, **Retry**, plus the manual-only Disregard, Blacklist, Archived, Rejected, Human Review), `Date Scraped` (date), `ATS Match Score` (number), `Tailored Resume Link` (url), `Date Applied` (date), `Hiring Manager` (rich_text), `Hiring Manager LinkedIn` (url). The live DB also carries `Notes` (rich_text), `Referral Contact` (rich_text), and `Job ID` (unique_id), none of which any stage reads or writes. `_notion_write_job()` additionally writes `Posted Date` (date), `Source` (rich_text), `Applicant Count` (number), and `Salary Range` (rich_text) when present on the job dict — add these properties (exact names/types) for Step 6's multi-source fields to land; their absence doesn't break the write (each is only added to `props` when the job dict has a value), it just means those columns stay empty. `Sponsorship` (select — yes/no/unknown) and `Scoring Attempts` (number) back the stage 1 scoring-retry queue (see below) and are written the same optionally-present way. `Enrichment Attempts` (number) backs the "Interested" intake enrichment-retry ceiling the same optionally-present way (see below). `Missing Keywords` (rich_text, comma-separated) is written the same optionally-present way by stage 1's `score_jobs_batch()` results and read back by `db_get_jobs()`/`_page_to_job()` into a list — stage 2 reads it as a prioritization hint for tailoring (see below); its absence doesn't break either stage, it just means stage 2 has no Stage-1 hint to work from. Stage 7 (auto-apply) writes `Apply Channel` (select), `Apply Attempts` (number), `Needs Human Reason` (rich_text), and `Application Log` (rich_text) the same optionally-present way, and needs six new `Status` options: `Application Queued`, `Applying`, `Needs Human: Captcha`, `Needs Human: Auth`, `Needs Human: Question`, `Apply Failed`. **Run `python scripts/setup_notion_schema.py --apply` once to add all ten** — unlike `pages.update` (which silently ignores an unknown select option), the `databases.update` endpoint *can* extend the schema, so this part is scriptable; the script is idempotent, dry-run by default, and resends existing Status options with their ids so none are dropped. **`Retry` is not auto-created by the Notion API — add it to the `Status` select's options by hand once**, or `db_update_status`/`db_add_job` calls that try to set it will silently fail to apply that property (the page still gets created/updated, just without the new status) — the same applies to stage 7's six new options above, which is exactly why stage 7 writes status via `db_update_status_verified()` (writes, re-reads, and skips the job with a loud log if Notion ignored it) rather than `db_update_status()`. The job description is **not** a property — it is cached in the page **body** (paragraph blocks) by `db_add_job` / `db_add_job_linked` and read back by `db_get_job_description()`.
- **"Interested" intake enrichment reliability:** `enrich_job_url()` (`scripts/sources.py`) returns `None` when a hand-picked job URL can't be enriched (e.g. `generic_url_fetch()`'s JSON-LD probe and raw-tag-stripped fallback both come up short on a JS-rendered career page). `ingest_interested_from_notion()` never scores against a blank JD — on a failed enrichment it increments `Enrichment Attempts` and leaves the row as `Interested` for the next `--ingest` run, mirroring `rescore_retry_jobs()`'s ceiling below. Once `Enrichment Attempts` exceeds `MAX_ENRICHMENT_ATTEMPTS` (`config/settings.py`, default 3), the row is promoted to `Scraped` with a `Notes` marker ("enrichment failed — add JD manually") instead of retried forever. `generic_url_fetch()` itself tries a schema.org `JobPosting` JSON-LD block (`<script type="application/ld+json">`) before falling back to raw `<title>`/tag-stripped text — many ATS-hosted and SEO-conscious career pages emit this even when the visible DOM is a client-rendered SPA shell, so it can recover a real `title`/`company`/`location`/`description` where the old tag-stripping fallback returned blank fields or too little text. If both the JSON-LD probe and the raw-text fallback come up short (a genuine client-rendered SPA shell with no server-rendered JobPosting data at all), it falls back once more to `_headless_fetch()` — a headless Chromium render via Playwright (optional dependency — `pip install -r requirements-optional.txt`, not part of the default `requirements.txt` install since nightly CI never exercises it; run `playwright install chromium` after installing) — and retries the identical extraction against the hydrated HTML. `_headless_fetch()` returns `None` (never raises) if Playwright isn't installed or the render itself fails, so its absence/failure degrades to the exact same "treat as enrichment failure" behavior as before this fallback existed.
- **Stage 1 scoring reliability:** `score_jobs_batch()` never fabricates a placeholder score. On a failed AI call (after `ai_chat`'s own 3-attempt retry with backoff) or a URL missing from the response, that job comes back `scored: False` and is written to Notion as `Status = "Retry"` with an empty ATS score — no fabricated `50`. `rescore_retry_jobs()` runs at the top of every stage 1 `run()`, right after `ingest_interested_from_notion()`: it re-scores every `Retry` row from its already-cached JD body (**no repeat Apify call**), incrementing `Scoring Attempts` each pass. Once `Scoring Attempts` exceeds `MAX_SCORING_ATTEMPTS` (`config/settings.py`), the job is promoted to `Scraped` with an empty score rather than retried forever. The same scoring call also classifies `company_type` (`product | staffing_or_consulting | agency | unknown`); a job whose type is in `SKIP_COMPANY_TYPES` is dropped (logged `[STAFFING/AI]`) the same way a sponsorship-denying JD is — but only when `scored` is `True`, so an unscored/failed batch is never dropped on an `"unknown"` `company_type`. `ai_chat()`/`ai_chat_blocks()` in `scripts/utils.py` retry transient errors (timeouts, 429/5xx) with exponential backoff and raise `AIChatError` on final failure, or `AIUsageCapError` immediately (no blind retry) on a detected Claude Code subscription usage-cap error.
- **Stage 2 keyword hint + post-tailor verification:** `tailor_resumes_batch()`/`_tailor_resume_single()` pass each job's stored `missing_keywords` into the tailoring prompt as a hint to verify against the full JD, not a checklist to blindly inject — Stage 1's list comes from a truncated JD excerpt, so the model still does its own extraction from the full JD and may find more (or discard a Stage-1 hint that doesn't actually fit). After `save_resume()`, `run()` calls `verify_tailored_score()` (reuses stage 1's `score_jobs_batch()` contract against the *tailored* resume text) and logs `ATS: {before} → {after}`; if `after` is below `MIN_TAILORED_ATS_SCORE` (`config/settings.py`, default 75), it logs a `⚠` warning only — it does not retry tailoring or change Notion status, matching the pipeline's existing non-blocking "log it, human decides in Notion" pattern.
- **Output dirs:** Auto-created by `ensure_dirs()` on first run
- **Nightly run output (GitHub Actions):** the runner's filesystem is discarded when the job ends, so `.github/workflows/nightly-pipeline.yml` ends with an `actions/upload-artifact@v4` step publishing all of `output/` as a single per-run bundle — download it from the run's summary page (GitHub zips it for you; no manual zip step). `if: always()` so a crashed run's partial output and stage 7 screenshots are still retrievable, `if-no-files-found: warn` so a failure before `output/` exists doesn't turn the run red, 30-day retention. This lives **only** in the workflow YAML — no `run.py` flag, no bundling code in the pipeline — so local runs never trigger it and keep writing to `output/` as before. Guarded by `tests/test_nightly_workflow_artifact.py`. A separate "Publish tailored resumes to tailored-resumes branch" step (gated by a workflow-level `permissions: contents: write`) pushes `output/resumes/*.docx` to a dedicated `tailored-resumes` orphan branch — self-bootstrapped on first run, additive only (never wipes earlier runs' files, since an older Notion row may still point at one) — so Notion's `Tailored Resume Link` can carry a stable `raw.githubusercontent.com` URL instead of a dead `file://` path. `scripts/stage2_tailor.py`'s `_tailored_resume_link()` picks the scheme via the `GITHUB_ACTIONS` env var, same guard pattern as `_load_local_env()`; local runs keep writing `file://` unchanged. Guarded by `tests/test_nightly_workflow_publish_resumes.py` and `tests/test_stage2_resume_link.py`.
- **Gmail optional:** Stage 4 `--send` requires `config/gmail_credentials.json` (Google Cloud OAuth)
- **All secrets are env-sourced:** every key in `config/settings.py` (`NOTION_API_KEY`, `APIFY_API_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `HUNTER_API_KEY`) is read via `os.environ.get(...)` — never hardcode a live value into that file, even locally. Locally, `config/settings.py`'s `_load_local_env()` auto-loads a git-ignored `.env` in the repo root (copy `.env.example` → `.env`) before any of those `os.environ.get(...)` calls run; it's a no-op under `GITHUB_ACTIONS`, where the same keys come from repo secrets (`.github/workflows/nightly-pipeline.yml`) instead. `NOTION_SCRATCH_PAGE_ID` and `NOTION_RESTRICTED_COMPANIES_PAGE_ID` follow the same env-sourced pattern but are **optional** — see "Scratch-note intake" and "Restricted-sponsorship company list" above — the features they back no-op when unset, unlike the required keys in this list. `NOTION_DB_ID` is env-sourced with **no hardcoded default** (`os.environ.get("NOTION_DB_ID", "")`) — a fork provisions its own tracker via `python run.py --init` (which writes the id to `.env`), or sets it by hand; `python run.py --setup` validates the live schema (via `provision_notion.validate_schema()`) and flags an unset/broken id. Existing owners must add their id to `.env` once (the literal was removed). `NOTION_SCRATCH_PAGE_ID` is set the same way by `--init` but stays optional.
- **`HUNTER_API_KEY` / `LEAD_ACTOR`:** only consumed by `scripts/spike_phase0_leads.py`, the Step 7 (communications subsystem) Phase 0 spike — not part of the 6-stage pipeline above. See `docs/backlog/step-7-communications-subsystem.md`.
- **`scripts/autoapply.py` / `scripts/autoapply_browser.py`:** Stage 7, the Step 10 Auto-Apply subsystem (Phases 1–2 landed; deliberate submit deferred to Phase 3). Wired into `run.py` as `--stage 7` / `--stage 7 --fill` (plus `--dry-run` / `--limit` for sampling). See the "Stage 7 Auto-Apply" section above and `docs/backlog/step-10-auto-apply-subsystem.md`.
- **`scripts/autoapply_profile.py`:** Stage 7's one-time answer wizard (`run.py --setup-profile`, or `--show`). Writes the git-ignored `config/application_profile.json` that `config/settings.py` overlays over the `APPLICATION_PROFILE` / `APPLICATION_ADDRESS` / `EEO_RESPONSES` / `COMMON_QUESTION_PRESETS` defaults — so personal application answers stay out of version control and aren't edited into a checked-in file. Missing/corrupt file = defaults stand. See the "Stage 7 Auto-Apply" section above.
- **`scripts/provision_notion.py`:** fork onboarding — creates the "Careerpilot-ai" page + **all three** databases (Job Search Tracker with the full schema/all 21 Status options, a clean single-URL-column Job Link Scratch Pad, and a clean single-company-name-column Restricted Sponsorship Companies) under a page the forker shared with their integration; returns the new ids. Owns the canonical `STATUS_OPTIONS` / `TRACKER_PROPERTIES` (single source of truth — `setup_notion_schema.py` imports the Stage-7 subset from it so create/patch can't drift) and exposes `validate_schema()` used by `run.py --setup`. Invoked by `python run.py --init`; also runnable standalone (`--parent-page <id>`) as the file-fallback path. Tolerates an API that rejects the `unique_id` `Job ID` column (retries without it — no stage reads it).
- **`scripts/setup_notion_schema.py`:** one-time, idempotent Notion schema migration for Stage 7 on a **pre-existing** DB — `--apply` adds the six new `Status` options and four new properties; dry-run by default, resends existing Status options with their ids so none are dropped, and reads back to verify. Run once before the first real (non-dry) Stage 7 run. (A DB freshly made by `provision_notion.py` already has all of these — this script is for older/hand-built trackers.)
- **DOCX resumes:** Stage 2 copies the base resume `.docx` (`RESUME_TEMPLATE_PATH`, default `config/resume.docx`) and applies targeted `{old → new}` keyword edits **in-place** via `extract_docx_text()` / `apply_docx_edits()` in `scripts/render_docx.py`, preserving formatting (also writes a `.txt` mirror). `render_docx.convert_docx_to_pdf()` (headless LibreOffice) produces the PDF fallback Stage 7's browser fill uses when a live form's upload field rejects `.docx` — see "Stage 7 Auto-Apply" above. The legacy Jinja2/`docxtpl` render path (`render_docx.render()` + `config/resume_template.docx`, scaffolded by `scripts/make_resume_template.py`) is no longer used by the default flow.

## docs/ directory scope: refinement-plans vs. backlog

`docs/refinement-plans/` holds a plan **while it's still at idea/discussion level** — design not
finalized, or finalized but deliberately deferred pending a trigger. `docs/backlog/` holds a story
**once it's finalized and lined up to be implemented**.

A plan moves in exactly one direction: refinement-plans → backlog, never the reverse. When a plan
is finalized and queued: fold its content into a `docs/backlog/step-N-*.md` story — condense the
"why" (sources considered/rejected, binding decisions, risks) alongside the implementation
checklist — then **delete** the refinement-plan doc. Don't leave the backlog story as a thin
summary pointing back at a "full spec" refinement doc; that's the duplication this rule exists to
avoid. One doc per story once it's queued. See `docs/backlog/README.md` and
`docs/refinement-plans/README.md` for the same rule stated from each side.

## Testing a Change

**Rule of thumb: every change ships with a test — no exceptions, for any agent working in this repo.**

1. Touched `scripts/*.py` or `run.py` logic? Add or update a pytest test under `tests/` in the
   same change, following the existing contract-test pattern (`patch_ai_chat`/`patch_notion_db`
   fakes from `tests/conftest.py`; see `tests/test_stage1_auto_review_gate.py` or
   `tests/test_stage2_sponsorship_gate.py` for reference). Run `pytest -v` — it's mocked, needs
   no API keys/Notion/Claude Code login, and finishes in ~1.5s — and make sure it's green before
   calling the change done. Stage 7's Layer 2 tests are the one exception: they drive a real
   Chromium against a local `file://` fixture, so they're marked `browser` and **deselected by
   default** (`addopts = -m "not browser"` in `pytest.ini`) to keep the default suite fast and
   CI browser-free. Touching `scripts/autoapply_browser.py`? Also run `pytest -m browser`
   (~80s, needs `playwright install chromium`).
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
