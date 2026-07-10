# Implementation README — Hybrid AI Provider Setup + Graceful Failure

> Companion to [`ai-failure-analysis.md`](ai-failure-analysis.md). This documents the approved
> implementation plan. **Not yet implemented** — use this as the spec when executing.

## Problem recap

The API→Agentic migration (feat/maverick) moved all AI calls onto the Claude Code subscription.
Two problems resulted:

1. **Reliability** — `score_jobs_batch()` (`scripts/stage1_scrape.py:356-381`) catches *all*
   exceptions and silently assigns every job a default ATS score of **50** (also for jobs the
   model omits from its response, lines 427/566). A failed SDK/CLI call writes fake scores to
   Notion with zero indication. No retry logic exists anywhere in the codebase.
2. **Session-limit drain** — every `_chat_claude_code()` call (`scripts/utils.py:99-107`) spawns
   a fresh `claude` CLI process (full session overhead, no prompt caching), and `workflow.py`'s
   agentic loop runs up to 60 uncached Sonnet turns with the resume re-sent every turn — the
   user's 5-hour usage window gets consumed by routine pipeline runs.

## Tradeoff analysis: metered API vs subscription agentic

| | Metered API (`claude`) | Subscription agentic (`claude_code`) |
|---|---|---|
| Cost | per-token $; Haiku bulk ≈ $3–5/mo | $0 marginal |
| Limits | none (rate limits only) | hard 5-hr usage cap, shared with interactive Claude Code use |
| Prompt caching | works (already wired in `_chat_claude` / `ai_chat_blocks`) | none |
| Per-call overhead | one HTTP call | CLI process spawn + full agent session per call |
| Best fit | unattended/bulk, many small calls | interactive, few big attended calls |

### Chosen hybrid (user-confirmed decisions)

- **Tier split**:
  - **fast tier** (stage 1 batch scoring, stage 3 outreach — many small calls) → **metered API,
    Haiku** (~$3–5/mo, zero session drain, caching restored)
  - **quality tier** (stage 2 tailoring, stages 5/6 — few, attended calls) + interactive
    `workflow.py` → **subscription**
- **Failover**: usage-cap error on subscription → one-time fallback to metered API
  (`ANTHROPIC_API_KEY` will be set by the user).
- **Scoring failure after retries** → save the job with an **empty ATS score** and
  `Status = Retry`, so the next Stage 1 batch re-scores it. Never a default 50.
- **Bulk runs**: steer to `run.py` **and** slim `workflow.py` with a batched scoring tool (both).

This refines §1 of `plan/reliability-filtering-networking.md` (which recommended all-metered);
the tier split satisfies the added "doesn't cost too much" constraint. §2/§3 of that doc are
untouched.

---

## Changes to implement

### 1. `config/settings.py` — tier routing config

- Add `ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")` (env-sourced; settings must
  capture it before any `os.environ.pop`).
- Replace `STAGE_AI_PROVIDER` with tier routing (keep the name defined = `""` for backward
  compat with existing imports):

```python
AI_ROUTING = {
    "fast":    {"provider": "claude",      "model": "claude-haiku-4-5"},  # metered — stages 1, 3
    "quality": {"provider": "claude_code", "model": "sonnet"},            # subscription — stages 2, 5, 6
}
ALLOW_METERED_FALLBACK = True   # on subscription usage-cap error, retry once via metered API
MAX_SCORING_ATTEMPTS   = 3      # give up re-scoring a Retry job after this many passes
```

- Keep `AI_PROVIDER` / `AI_MODEL_OVERRIDE` / `QUALITY_MODEL` as the fallback when `AI_ROUTING`
  is empty/absent (current behavior preserved if the user blanks the routing).

### 2. `scripts/utils.py` — routing, retries, failover, typed errors

- New `_resolve_route(quality: bool) -> tuple[provider, model]`: reads `AI_ROUTING[tier]`; if the
  tier's provider is `"claude"` but `ANTHROPIC_API_KEY` is empty, fall back to `claude_code`
  with a one-time warning log. Falls back to legacy `_active_provider()` / `_resolve_model()`
  when `AI_ROUTING` is unset.
- `ai_chat()` dispatches via `_resolve_route`; backends receive the resolved model (adjust
  `_chat_*` signatures to take `model` instead of re-resolving internally).
- Retry wrapper inside `ai_chat`: **3 attempts, exponential backoff (≈2s/8s)** on transient
  errors (timeouts, 429/5xx, CLI process failures). Distinctly detect the subscription
  **usage-cap** error (match SDK/CLI error text, e.g. "usage limit" / "rate limit reached"
  patterns) — do **not** blind-retry it; instead, if `ALLOW_METERED_FALLBACK` and key present →
  one failover call via `_chat_claude`; else raise `AIUsageCapError` with a clear
  "wait for window renewal, then re-run (re-runs skip completed jobs)" message.
- New exceptions: `AIChatError` (final transient failure), `AIUsageCapError` — so callers can
  react specifically instead of `except Exception`.
- `ai_chat_blocks()` gets the same route resolution (the structured/cached path already exists
  for `"claude"`; the fast tier now benefits from it).

### 3. `scripts/stage1_scrape.py` — kill the silent default-50, re-queue for retry

**3a. Remove the fallback.** `score_jobs_batch()`: delete the blanket
`except Exception → score 50` (lines 356-381). Retries now live in `ai_chat`. On final failure
return `None` for the whole batch and `log()` the error loudly. For jobs the model omitted from
an otherwise-valid response: `score: None` (not 50).

**3b. Re-queue instead of dropping.** When a job's score is `None`, still write it to Notion —
with an **empty** ATS score and `Status = "Retry"` rather than `"Scraped"`. The JD is cached in
the page body as usual, so the retry costs **no Apify call** on the next run. Nothing is lost
(Stage 1 only scrapes the past 24h, so a skipped job is gone for good), and an empty score is
visibly distinct from a real 50 in the tracker.

- `run()` (lines 561-592): pass `status="Retry"` to `db_add_job` when unscored; log
  `⚠ queued for RETRY (scoring failed)`.
- `ingest_interested_from_notion()` (lines 422-437): when unscored, **leave the page as-is**
  (do not call `db_add_job_linked`, which promotes to Scraped). Set `Status = "Retry"` and
  cache the fetched JD in the body so the next run rescores without re-enriching.

**3c. Drain the retry queue at the top of Stage 1.** New `rescore_retry_jobs(resume)`, called in
`run()` right after `ingest_interested_from_notion()` (line 531):

1. `db_get_jobs(status="Retry")` → pull the queued pages.
2. Read each JD back from the page body via `db_get_job_description(page_id)` (already exists,
   `utils.py:506`) — no Apify, no re-scrape.
3. Feed them through the same `score_jobs_batch()` used by the scrape path.
4. On success: `db_update_status(page_id, "Scraped", {...})` + write the real ATS score.
   On failure: increment the attempt counter (below) and leave in `Retry`.

**3d. Attempt cap — do not retry forever.** Add a `Scoring Attempts` (number) property to the
Notion schema. `rescore_retry_jobs()` increments it on each failed pass; once it exceeds
`MAX_SCORING_ATTEMPTS` (new setting, default `3`), promote the job to `Scraped` with an empty
score and log `⚠ giving up on scoring after N attempts` — the job stays reviewable by hand
rather than looping every morning.

**3e. Plumbing this needs.**

- `_notion_write_job()` (`utils.py:300-320`) hardcodes `"Status": {"select": {"name": "Scraped"}}`
  — thread a `status: str = "Scraped"` param through it and through `db_add_job()`.
- `_EXTRA_TO_NOTION` (`utils.py:324-329`) needs a `scoring_attempts` →
  `{"Scoring Attempts": {"number": v}}` mapping, and an `ats_match_score` mapping so
  `db_update_status()` can write the real score when a retry finally succeeds.
- `_page_to_job()` (`utils.py:266`) should surface `scoring_attempts` alongside `ats`.

**3f. End-of-run summary:** `N scored / M queued for retry / K gave up after {MAX} attempts`.

### 3.5 ⚠ Blocking bug: `Interested` / `Retry` rows self-match on dedup

`ingest_interested_from_notion()` (lines 396-401) calls `db_find_job_by_url(page["url"])` for
each Interested page. But that page **lives in the same jobs DB and has that Job URL**, so
`_query_db(filter_={"property": "Job URL", "url": {"equals": url}})` (`utils.py:449-458`) matches
the page *itself*. Every Interested row with a URL therefore takes the
`⊘ Already in DB, retiring Notion row` branch and is promoted straight to Scraped **with no
score and no JD** — manual intake silently degrades today, and a `Retry` row would be retired
before it was ever rescored.

**Fix (prerequisite for §3c):** give `db_find_job_by_url()` an `exclude_page_id: str = ""`
parameter and skip a hit whose `id` equals it — the ingest/retry paths pass the row's own
`page_id`. Alternatively filter the query to exclude `Status ∈ {Interested, Retry}`. Either way,
the check must ask "is this job tracked under a **different** page?"

The same trap applies to the `existing_urls` snapshot in
[`../notion-dedup-snapshot-TODO.md`](../notion-dedup-snapshot-TODO.md): build that set from rows
whose status is **not** `Interested`/`Retry`, or a queued row will be dropped as a duplicate of
itself on the next scrape.

### 4. `workflow.py` — batched scoring tool + resilient loop

- **New `score_jobs` jobpipe tool**: wraps `stage1_scrape.score_jobs_batch(jobs, resume)`
  (fast tier → metered Haiku, one call per batch). Register in `TOOLS` / `_TOOL_IMPL` following
  the existing `_make_tool` pattern (workflow.py:282-293).
- Update `_task_morning` / `_task_scrape` prompts: "score via the `score_jobs` tool in one
  batched call" instead of the agent scoring each job in its own context — cuts turn count and
  context growth substantially.
- **Move the `os.environ.pop("ANTHROPIC_API_KEY")` (line 34) to *after* the settings import
  (line 40)** so settings captures the key for the metered tool path while the SDK still
  authenticates via subscription (env stays clean before `query()` spawns the CLI).
- Wrap `_run()`'s streaming loop body in try/except: on failure print how many tool calls
  completed, distinguish usage-cap messages from transient errors, and note that re-running is
  safe (Notion status transitions + `check_job_in_db` make stages idempotent).

### 5. Notion schema — two additions

The tracker DB (`NOTION_DB_ID`) needs, **before any code runs**:

- `Status` (select) — add a **`Retry`** option to the existing list
  (Interested, Scraped, Reviewed, Resume Tailored, Applied, Outreach Sent, Interview Scheduled,
  Offer Received, Disregard).
- `Scoring Attempts` (number) — new property, blank/0 by default.

A missing or mistyped property silently breaks Notion queries and writes, so verify both in the
UI first. Update the "Notion database schema" section of `CLAUDE.md` to match.

Optionally add a `Retry` view to the tracker so queued jobs are visible at a glance.

### 6. Docs — `CLAUDE.md` + `run.py --setup`

- `check_setup()` in `run.py`: print the routing table (tier → provider/model), whether
  `ANTHROPIC_API_KEY` is present for the fast tier / failover, and the count of jobs currently
  sitting in `Retry`.
- `CLAUDE.md`: document the tier split, failover, the `Retry` status + attempt cap, the two new
  schema properties, and the guidance **`run.py` for scheduled/bulk runs; `workflow.py` for
  interactive one-offs** (its morning task now uses the batched `score_jobs` tool). Add `Retry`
  to the documented status pipeline.
- Write the final tradeoff analysis to `plan/problem/ai-api-agentic-tradeoff.md`.

## Files touched

`config/settings.py`, `scripts/utils.py`, `scripts/stage1_scrape.py`, `workflow.py`,
`run.py` (setup check only), `CLAUDE.md`, new `plan/problem/ai-api-agentic-tradeoff.md`,
plus the two Notion schema changes above.

**Not touched:** stages 2/3/5/6 call sites (they already pass `quality=` correctly and route
automatically through the new `ai_chat`), filtering logic.

**Interacts with:** [`../notion-dedup-snapshot-TODO.md`](../notion-dedup-snapshot-TODO.md) — if
that lands first, its `existing_urls` set must exclude `Interested`/`Retry` rows (see §3.5).

## Suggested order

1. §3.5 dedup self-match fix (unblocks everything, and fixes manual intake today).
2. Notion schema (§5) — `Retry` option + `Scoring Attempts`.
3. §1 + §2 routing, retries, failover.
4. §3 default-50 removal + retry queue.
5. §4 workflow tool, §6 docs.

## Verification checklist

1. `python run.py --setup` → routing table shows fast→claude(haiku) / quality→claude_code(sonnet),
   key present, retry-queue count printed.
2. **Self-match fix (§3.5):** add a row by hand with `Status = Interested` + a Job URL, run
   `python run.py --ingest` → it must be **enriched and scored**, not silently retired to Scraped
   with a blank score.
3. **Reliability + retry queue:** temporarily point the fast tier at an invalid model → run
   `python run.py --stage 1` with one role / small `maxItems`. Confirm: 3 retries with backoff in
   the log; jobs land in Notion with an **empty** ATS score and `Status = Retry` (no 50s); summary
   reads `0 scored / N queued for retry`.
4. **Retry drains:** restore the valid model, re-run `python run.py --stage 1`. Those same rows
   should be re-scored **from the cached JD with no Apify call**, get real scores, and flip to
   `Scraped`.
5. **Attempt cap:** leave the invalid model in place and run Stage 1 `MAX_SCORING_ATTEMPTS + 1`
   times. Confirm `Scoring Attempts` increments each pass and the job finally promotes to
   `Scraped` with an empty score and a `⚠ giving up` log, rather than looping forever.
6. **Routing:** a normal stage 1 run logs the fast tier on metered Haiku;
   `python run.py --stage 3 --company <X>` → also metered; a stage 2 tailor → quality tier on
   subscription.
7. **Failover:** temporarily make `_chat_claude_code` raise a fake usage-cap error → confirm a
   single failover to `_chat_claude` (metered) with a warning, not 3 blind retries.
8. **workflow.py:** `python workflow.py --task scrape` → agent calls `score_jobs` once per batch
   (visible in the `⚙` tool echo), turn count in the ResultMessage drops vs before; interrupt a
   run mid-way and confirm the new except path prints completed-call count + re-run guidance.
