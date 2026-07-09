# Pipeline reliability, filtering, and networking-sourcing plan (baseline: `feat/maverick` @ PR #5)

## Context

Rebaselined against the actual tip of `feat/maverick` (commit `cec948f`, the head of open PR #5, "Notion 'Interested' intake, Indeed scraping, and provider model fixes") — not the `claude/main-maverick-diff-kni19i` dev branch, which had reverted several of these changes. All findings below were confirmed by reading `feat/maverick`'s real files, with exact line numbers.

User decisions carried over from clarifying questions:
- AI provider: deferred to recommendation → keep the automated/unattended pipeline off subscription-cap risk, add robustness.
- Networking/LinkedIn sourcing: explicit choice → automated scrape with a manual approval gate before any outreach is drafted or sent.

(Design-role support was considered but is explicitly out of scope — dropped per user correction.)

---

## 1. AI-call reliability (subscription vs API) — confirmed root cause

`feat/maverick` genuinely runs subscription mode by default and reproduces the reported bug exactly:
- `config/settings.py`: `AI_PROVIDER = "claude_code"` (line 125), `STAGE_AI_PROVIDER = ""` (line 131, falls through to `AI_PROVIDER`).
- `scripts/utils.py` `_chat_claude_code()` (lines 99-107) does `os.environ.pop("ANTHROPIC_API_KEY", None)` then drives the Claude Agent SDK (`query()`/`ClaudeAgentOptions`, single-shot `max_turns=1`) for stage-script calls (run.py path).
- `workflow.py`'s `_run()` (lines 781-816) drives the same SDK's full agentic tool loop (`ClaudeAgentOptions(..., max_turns=_MAX_TURNS)`, `query()`), also forcing subscription auth (workflow.py:34).
- **No retry, backoff, or checkpoint logic exists anywhere** in either file (confirmed: zero matches for `retry`/`checkpoint`/`RateLimit`/`backoff`). Conversation state lives only in the local async generator — never persisted. A usage-limit error (or any transient failure) surfacing mid-`workflow.py` run kills the process with no resume path; the next invocation starts a brand-new task prompt from zero.

**Analysis:** Subscription mode has no per-token cost but a hard usage cap outside the pipeline's control — a poor fit for an unattended/scheduled run (the CLAUDE.md-documented default entry point, `workflow.py`, is meant to run daily). Metered API has no cap, just small per-token cost at this pipeline's volume (a handful of jobs/day), and doesn't depend on an interactive `claude /login` session being alive wherever the pipeline runs.

**Recommendation:**
- **Default the automated pipeline (`workflow.py`) to metered API** (`AI_PROVIDER = "claude"`) to eliminate usage-cap risk for unattended runs — this is the one failure mode that actually cost the user real time. Keep `"claude_code"` available as an opt-in for interactive, supervised, ad hoc runs (a single outreach draft while at the keyboard, where waiting out a cap is a non-issue).
- The codebase already has the plumbing for a split: `STAGE_AI_PROVIDER` exists precisely to let `run.py`'s stage scripts use a different provider than `workflow.py`. Use it (or make `workflow.py` read the same override) rather than adding new config surface.
- **Add retry-with-backoff** around the SDK/API call points — `workflow.py`'s `query()` loop in `_run()` and each `_chat_*` backend in `scripts/utils.py` — for transient errors (rate limit, 5xx, timeout): 3 attempts, exponential backoff. Explicitly do **not** blind-retry a usage-cap-exceeded error; detect that error distinctly and fail with a clear "wait for renewal, then re-run" message instead.
- **Don't build a heavyweight conversation-checkpoint file** — over-engineered for what's needed. The pipeline already has per-job idempotency (Notion status transitions + `check_job_in_db`/status-filtered queries mean a re-run naturally skips already-completed jobs). The actual gap is just that `_run()`'s loop currently lets an exception crash with a raw stack trace and no guidance. Fix: wrap the loop body in `try/except`, print how many jobs/tool-calls completed before the failure, and tell the user re-running is safe and will skip completed work — leaning on the idempotency that already exists instead of duplicating it.
- Also fix the same missing exception handling around `score_jobs_batch()`'s AI call in `stage1_scrape.py` and the InMail/outreach AI calls in `stage3_outreach.py`, which have the identical gap.

## 2. Better filtering: product companies, real sponsorship

**Current state is more advanced than assumed** — confirmed in `scripts/stage1_scrape.py` and `config/settings.py`:
- `is_skipped_company()` (stage1_scrape.py:265-279) already does two layers: exact/substring `SKIP_COMPANIES` (~90 entries, settings.py:22-44) + substring `SKIP_COMPANY_KEYWORDS` (settings.py:49-70, e.g. "consulting", "staffing", "solutions llc", "recruit", "resources"). `is_skipped_title()` (stage1_scrape.py:282-286) checks `SKIP_TITLE_KEYWORDS` (settings.py:74-86).
- Sponsorship already has two layers: a regex pre-filter `jd_says_no_sponsorship()` (stage1_scrape.py:290-317, applied at line 500) plus an LLM classification inside `score_jobs_batch()` (lines 322-381, applied at line 570-572) that also drops `"no"`. **The remaining gap**: jobs the LLM classifies `"unknown"` (the common case — most JDs never mention sponsorship either way) still pass through untouched. This, not weak filtering, is why no-sponsorship roles still appear — it's an inherent ambiguity problem, not a bug.
- **Company-type (product vs. staffing/consulting) is still 100% substring matching — never AI-classified.** `score_jobs_batch()`'s prompt (lines 337-355) only asks for `score` and `sponsorship`, never company type. This is the direct, confirmed cause of "still mostly consulting/staffing companies" — a fixed keyword/name list structurally cannot keep up with every staffing shell's naming pattern, no matter how large.
- A drop-reason audit log already exists (`_open_drop_log`/`_log_drop`, lines 444-467) — just needs a new reason category, not new infrastructure.
- Minor correctness bug found: `"Qualcomm"` is in `SKIP_COMPANIES` (settings.py:43) despite being a real product company — false positive to remove.
- `TARGET_COMPANIES` (settings.py:15) is defined but never referenced in `stage1_scrape.py` — dead config.

**Plan:**
- **a. Add AI company-type classification to the existing batched call** — extend `score_jobs_batch()`'s JSON response schema (stage1_scrape.py:322-381) to also return `company_type: product | staffing_or_consulting | agency | unknown`, using the company/JD text already in that prompt (no extra API call). Drop `staffing_or_consulting` the same way `sponsorship == "no"` is dropped today (mirror the pattern at lines 570-572), logging the reason via the existing `_log_drop()`.
- **b. Remove the `"Qualcomm"` false positive** from `SKIP_COMPANIES`, and spot-check the rest of the list for similar misses while touching this file.
- **c. Surface sponsorship ambiguity instead of guessing**: write the `sponsorship` value (and ideally a short reason) to a Notion property so `"unknown"` rows are visible/reviewable rather than invisibly passed through. Add an opt-in `SPONSORSHIP_MODE = "lenient" | "strict"` setting where `"strict"` also drops `"unknown"` for users who'd rather over-filter than under-filter.

Files touched: `config/settings.py`, `scripts/stage1_scrape.py`.

## 3. Networking-based sourcing (hiring managers, recruiters, "we're hiring" posts)

**Current state confirmed: zero capability, even on `feat/maverick`.** Only two Apify actors exist, both job-listing scrapers (`LINKEDIN_ACTOR = "bebity~linkedin-jobs-scraper"`, `INDEED_ACTOR = "bebity~indeed-scraper"`, settings.py:36,38). `LINKEDIN_SESSION_COOKIE` (settings.py:93) is used exactly once, in `_linkedin_payload_base()` (stage1_scrape.py:77-92), purely to enrich job listings with `applicant_count`/`salary_range` — it never touches a people-search or post-search endpoint. `stage3_outreach.py`'s InMail drafting (`draft_inmail_batch()`/`_draft_inmail_single()`, lines 222-302) works purely from job/company/ATS-score data and takes no contact name at all. The separate warm-referral path (`draft_warm_referral()`, lines 36-48) *does* accept a `contact_name`/`contact_role`, but only ever supplied manually via `--contact`/`--contact-role` CLI flags — nothing populates it automatically. The "Hiring Manager"/"Hiring Manager LinkedIn" Notion properties exist as schema plumbing (`_page_to_job()`, `_EXTRA_TO_NOTION`, utils.py:266-282, 324-329) but no code path ever writes to them — manual-entry-only. There is no "Leads" database concept; everything lives on the single jobs table.

**Plan (automated discovery + manual approval gate):**
1. **Research spike first**: identify and validate a working Apify actor for LinkedIn post/people search (pricing, output schema, ToS) before committing to an actor ID — don't assume one sight-unseen, same as the two actors already in use were presumably vetted.
2. **New sourcing stage** (`scripts/stage7_network_sourcing.py`), built on the same generic `_apify_run()` pattern already used for LinkedIn/Indeed (stage1_scrape.py:47-72) so it's a drop-in third actor rather than new plumbing:
   - Search for hiring-signal posts ("we're hiring", "join our team", referral asks) filtered by target companies/roles.
   - Extract poster name, headline, company, post text/URL.
   - Classify poster role (recruiter / technical recruiter / hiring manager / engineer) via a cheap regex first pass on the headline, falling back to an LLM classification for ambiguous cases — same "add a field to a batched AI call" pattern as §2a.
   - Cross-check the poster's company against the product-company filter built in §2 (reuse `is_skipped_company()` + the new `company_type` classification) so leads are limited to real product companies.
3. **Separate Notion "Leads" database** (distinct schema from the jobs DB: Name, Title, Company, LinkedIn URL, Post URL/snippet, Status: `Identified → Approved → Messaged → Replied → Connected`) — keeps outreach targets separate from job postings, following the same `_notion_write_job()`/`_EXTRA_TO_NOTION`-style property-mapping pattern already used in `scripts/utils.py`.
4. **Manual approval gate**: leads land as `Identified`, never auto-messaged. Add `draft_connection_request(lead)` to `stage3_outreach.py`, reusing `draft_warm_referral()`'s existing contact-name-aware AI-drafting pattern (lines 36-48) — runs only for leads marked `Approved` in Notion, saving a draft to `output/outreach/` for manual review/send, exactly like today's cold-email/InMail gates. No automated connecting or messaging, ever.

**Risk notes to carry into implementation:** LinkedIn's ToS restricts automated scraping of member profiles/activity more strictly than job listings; treat this as higher-risk/experimental — rate-limit aggressively, keep the human-sends-manually gate non-negotiable, and don't skip the research spike in step 1.

---

## Verification

- **§1**: Force a transient error during a `workflow.py` run (e.g. temporarily invalid model name) and confirm retry/backoff engages and the failure message correctly distinguishes a real usage-cap error from a transient one; re-run after an interrupted run and confirm already-processed jobs are skipped (existing idempotency) rather than redone.
- **§2**: Run `python run.py --stage 1` with a small `max_results`; check `output/filter_logs/` to confirm a known staffing/consulting company not in `SKIP_COMPANIES` gets caught by the new `company_type` AI classification, confirm `"Qualcomm"` no longer gets dropped, and confirm sponsorship `"unknown"` jobs are now visible with a reason in Notion.
- **§3**: Run the new sourcing stage against a small batch; confirm leads land in the new Notion Leads database as `Identified` only, and that no message is drafted or sent until a lead is manually flipped to `Approved`.
