# PR #5 — Detailed Change Review

> **Notion 'Interested' intake, Indeed scraping, and provider model fixes**
> Base: `main` ← Head: `feat/maverick` · **+1715 / −678** · 18 files changed · State: **OPEN**
> Author: repo owner
> PR: https://github.com/your-username/local-n8n-engine/pull/5

This document is a file-by-file breakdown of everything in the PR, plus a prioritized
review log. Use it as the working checklist during detailed review.

---

## 1. What this PR does (at a glance)

The PR bundles four largely independent workstreams:

| # | Theme | Summary |
|---|-------|---------|
| A | **Data-layer rewrite** | Removes Supabase entirely; **Notion becomes the single source of truth**. JD moves from a Supabase column into the Notion **page body** (paragraph blocks). All `db_*` helpers reimplemented against the Notion API with pagination. |
| B | **Ingestion & sourcing** | Manual "Interested" intake from Notion (`--ingest`), Indeed scraper, LinkedIn Premium signals (applicant count / salary via `li_at` cookie), a 3-layer pre-scoring filter, and a drop-log. |
| C | **AI provider work** | New `claude_code` (Agent SDK / subscription) backend; `workflow.py` moved onto the SDK's native agentic loop; fixes to `_chat_gemini`/`_chat_codex` (`quality` flag) and gpt-5/o-series `max_completion_tokens`. |
| D | **Prompt & UX** | Batch tailoring (one AI call for all jobs + per-job fallback), stronger tailoring prompt, LinkedIn InMail drafts. |

---

## 2. File-by-file changes

### Code

| File | Change |
|------|--------|
| `scripts/utils.py` | **Core rewrite.** Supabase CRUD (`_get_db`, `.table("jobs")…`) replaced with Notion-backed CRUD (`_query_db` w/ pagination, `_page_to_job`, `_jd_blocks`). New `claude_code` backend (`_chat_claude_code`, `_sdk_text`, `_find_claude_cli`). `_is_reasoning_model()` for gpt-5/o-series. `_chat_gemini`/`_chat_codex` now honor `quality`. `_active_provider()` (respects `STAGE_AI_PROVIDER`). `sync_notion_to_supabase()` → no-op. JD now cached in / read from Notion page body. |
| `scripts/stage1_scrape.py` | Generic `_apify_run()`; `scrape_linkedin` (bebity actor, Premium cookie, applicant count, salary) + `scrape_indeed`; `scrape_job_urls` enrichment; `ingest_interested_from_notion`; 3-layer `_pre_filter` (company/title keyword denylists + US location + no-sponsorship regex + max applicants); drop-log writer; expanded no-sponsorship regex. |
| `scripts/stage2_tailor.py` | `tailor_resume` → `_tailor_resume_single` returning `(edits, keywords)`; new `tailor_resumes_batch` (one AI call, index/company matching); 3-phase `run()` (fetch JDs → batch call → apply); stronger `SYSTEM_PROMPT`. |
| `scripts/stage3_outreach.py` | New LinkedIn InMail path: `draft_inmail_batch`, `_draft_inmail_single`, `run_inmail`; `--inmail` / `--no-confirm` flags; `INMAIL_ATS_THRESHOLD` gate. |
| `workflow.py` | Rewritten from the metered `anthropic` client onto the **Agent SDK** (`claude-agent-sdk`). Tools exposed as in-process MCP server `jobpipe` (`mcp__jobpipe__*`); native agentic loop via `query()`; `os.environ.pop("ANTHROPIC_API_KEY")` to force subscription auth; `sync_disregard` tool → no-op. |
| `run.py` | `claude_code` added to provider pkg map & setup check (CLI presence via `shutil.which`); Supabase checks removed; new `--ingest` flag + `ingest_routine`; `evaluate_routine` no longer syncs. |
| `config/settings.py` | `AI_PROVIDER = "claude_code"`; `STAGE_AI_PROVIDER`; `AI_MODEL_OVERRIDE`/`QUALITY_MODEL` → haiku/sonnet; `SKIP_COMPANY_KEYWORDS`, `SKIP_TITLE_KEYWORDS`, expanded `SKIP_COMPANIES`; `LINKEDIN_SESSION_COOKIE`, `MAX_APPLICANT_COUNT`, `INMAIL_ATS_THRESHOLD`; `NOTION_API_KEY` → `os.environ.get`; Supabase keys & Anthropic/OpenAI literals removed. |
| `requirements.txt` | `claude-agent-sdk` added; `supabase` removed; `notion-client` pinned `>=2.2.1,<2.6` (2.6+/3.x dropped `databases.query`). |
| `config/resume.txt` | Content update (removed city line, added PROJECTS section, github handle). |
| `config/resume.docx` (base resume `.docx`) | Binary update. |

### Docs

| File | Change |
|------|--------|
| `CLAUDE.md` | Rewritten to **Notion-primary**; two-step flow; Interested intake; provider table w/ `claude_code`. |
| `README.md` | Two-step flow, file structure, intake; **⚠ still says "Supabase (primary)" in one line**. |
| `SETUP.md` | Base `.docx` tailoring section, Interested/Reviewed statuses; **⚠ still contains the Supabase `CREATE TABLE jobs` schema**. |
| `.claude/agents/notion-tracker.md` | **⚠ still describes Supabase as primary store.** |
| `.claude/agents/pipeline-orchestrator.md` | **⚠ still describes Supabase as primary store.** |
| `.claude/agents/resume-tailor.md` | Updated for in-place `.docx` edits; **⚠ references Supabase.** |
| `.claude/agents/outreach-drafter.md` | Updated for `no_confirm` gate. |
| `.claude/skills/run-local-n8n-engine/SKILL.md` | Two-step flow, provider notes; **⚠ mixed Supabase/Notion wording.** |

---

## 3. Review log (prioritized)

### 🔴 Must fix

- [ ] **1. Docs contradict each other and the code.** PR body claims "Supabase-primary / Notion-mirror," but code deletes Supabase and makes Notion primary. Tree now ships three conflicting stories:
  - `CLAUDE.md` / `run.py` → Notion is primary ✅ (matches code)
  - `README.md:~586` → "Data lives in **Supabase (primary)**" ❌
  - `SETUP.md` → still documents Supabase `CREATE TABLE jobs` + "tracked in Supabase" ❌
  - `notion-tracker.md`, `pipeline-orchestrator.md`, `resume-tailor.md` → all say **Supabase is primary**, describe deleted helpers (`_get_db`) ❌

  **Action:** make every doc Notion-primary and scrub all Supabase references.

- [ ] **2. Duplicate `_active_provider()` definition** in `scripts/utils.py` — same function pasted twice back-to-back (merge artifact). Delete one.

- [ ] **3. Live secrets committed.** `APIFY_API_TOKEN` still hardcoded in `config/settings.py`; the Anthropic/OpenAI/Supabase keys this PR removes remain in **git history**. Treat all as compromised — **rotate them** and source from env (or git-ignore `settings.py` with a `settings.example.py`).

### 🟡 Should look at

- [ ] **4. Dedup is now an N-network-call loop.** `_pre_filter()` calls `db_find_job_by_url()` per candidate; each runs a paginated Notion query. 2 sources × 25 × several roles ≈ 100+ sequential queries against Notion's ~3 req/s limit. Fetch existing URLs once into a set at the start of `run()`.

- [ ] **5. `str.strip("```json")` is not prefix-stripping** in `stage3_outreach.py:_draft_inmail_single` — strips any of the chars `` ` j s o n ``, can mangle valid output. Reuse `parse_json_response()` (the batch path already does).

- [ ] **6. Same-company batch collision** in `stage2_tailor.py:tailor_resumes_batch` — if the model omits `job_index` and two roles share a company, `by_company` collapses to one entry → identical edits for both. Make `job_index` mandatory or log the fallback.

- [ ] **7. Global env mutation as a chat side effect.** `_chat_claude_code` does `os.environ.pop("ANTHROPIC_API_KEY", None)`, permanently disabling the metered `claude` backend for the rest of the process. Comment/scope it.

### 🟢 Minor / nits

- [ ] **8.** New settings (`MAX_APPLICANT_COUNT`, `LINKEDIN_SESSION_COOKIE`, `INMAIL_ATS_THRESHOLD`) read via `import *` — a stale `settings.py` without them will `NameError`. The `getattr` guard added for provider keys isn't applied here.
- [ ] **9.** `safe = lambda ...` inside `run_inmail` (E731) — make it a `def`.
- [ ] **10.** `_chat_claude_code` calls `asyncio.run()` per invocation — fine today, but raises if ever called from inside a running loop.
- [ ] **11.** No tests touched; test plan is all-manual and unchecked. The data layer was fully rewritten — add at least one round-trip test (`db_add_job` → `db_get_jobs` → `db_get_job_description`).

---

## 4. Good parts (keep as-is)

- Provider `quality`-flag fix in `_chat_gemini`/`_chat_codex` — real bug fix (non-Claude providers previously ignored `QUALITY_MODEL`).
- `_is_reasoning_model()` + `max_completion_tokens` for gpt-5/o-series — correct.
- LinkedIn job-id regex split (`_JOB_ID_RE` preferred, delimited `\d{8,}` fallback) — avoids tracking-digit false matches.
- `parse_json_response()` now also handles outermost `[...]` arrays for batch responses.
- Notion CRUD correctly follows `has_more` / `next_cursor` pagination throughout.
- Batch-with-per-job-fallback pattern (tailoring & InMail) is a clean, resilient design.

---

## 5. Verdict

The **code is solid** — provider fixes and batch/fallback patterns are well done, and the
Notion-backed CRUD is clean and correctly paginated. The blocker is **coherence, not
logic**: contradictory docs describing a deleted Supabase architecture (#1), a duplicated
function (#2), and secrets still in the tree/history (#3). Request changes on those three
before merge; #4–#7 can be follow-ups.

---

*Generated as a review aid for PR #5. Update the checkboxes as items are resolved.*
