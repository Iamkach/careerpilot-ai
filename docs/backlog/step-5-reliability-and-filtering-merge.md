# Step 5 — Merge reliability (Plan 2) + filtering AI classification (Plan 1b)

**Priority:** P1 — resolves Conflicts C1/C2/C3; kills the most-cited defect in the whole analysis
(fabricated `score=50`).
**Depends on:** Step 4
**Blocks:** Step 6 (fingerprint dedup and retry queue share failure-handling patterns), Step 7
(benefits from this step's `classify_company_type()` decision, Conflict C4)
**Size:** L — touches `settings.py`, `utils.py`, `stage1_scrape.py`, `workflow.py`, `run.py`
**Source plan(s):**
[`refinement-plans/reliability/hybrid-agentic-migration-plan.md`](../refinement-plans/reliability/hybrid-agentic-migration-plan.md)
(primary spec) merged with
[`refinement-plans/filtering/stage1-filtering-rework.md`](../refinement-plans/filtering/stage1-filtering-rework.md)
§3-9 (Plan 1b, per Conflict C1 resolution: **Plan 2's failure model wins, Plan 1 contributes the
classification/filter logic**)

## Context

Two problems, one root cause: `score_jobs_batch()` (`stage1_scrape.py:356-381`) catches *every*
exception and fabricates `score=50, sponsorship="unknown"` for the whole batch, with nothing
logged or raised. No retry logic exists anywhere. Separately, every `_chat_claude_code()` call
spawns a fresh CLI process with no prompt caching, and `workflow.py`'s agentic loop can run up to
60 uncached turns — burning the user's 5-hour subscription usage window on routine runs.

**This story intentionally merges two plan documents.** Do not implement Plan 1's
`score_jobs_batch()` rewrite or its separate `ai_chat_retry()` wrapper — Plan 2's `Retry`-queue
failure model and in-`ai_chat` retry are strictly better (automatic recovery, no extra Apify call,
attempt-capped) and touch the exact same ~60 lines. Implementing both means rewriting one on top of
the other.

## What to do

### 1. `config/settings.py` — tier routing + the missing key

- Add `ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")`. **Correction from the
  refinement-plans README:** this key does not exist in settings today at all — both `utils.py:13`
  and `run.py:55` currently fall back to `""` via `getattr`. This must be *added*, not "moved."
- Replace `STAGE_AI_PROVIDER` with tier routing (keep the name defined for backward compat):
  ```python
  AI_ROUTING = {
      "fast":    {"provider": "claude",      "model": "claude-haiku-4-5"},  # metered — stages 1, 3
      "quality": {"provider": "claude_code", "model": "sonnet"},            # subscription — stages 2, 5, 6
  }
  ALLOW_METERED_FALLBACK = True
  MAX_SCORING_ATTEMPTS   = 3
  SKIP_COMPANY_TYPES = {"staffing_or_consulting"}   # deliberately NOT "agency" — see filtering plan §5
  ```
- Keep `AI_PROVIDER`/`AI_MODEL_OVERRIDE`/`QUALITY_MODEL` as the fallback when `AI_ROUTING` is
  empty.

### 2. `scripts/utils.py` — routing, retries, failover, typed errors

- New `_resolve_route(quality: bool) -> (provider, model)`: reads `AI_ROUTING[tier]`; if the
  tier's provider is `"claude"` but the key is empty, fall back to `claude_code` with a one-time
  warning. Falls back to legacy `_active_provider()`/`_resolve_model()` when `AI_ROUTING` is unset.
- `ai_chat()` dispatches via `_resolve_route`.
- Retry inside `ai_chat`: 3 attempts, exponential backoff (~2s/8s) on transient errors
  (timeouts, 429/5xx, CLI process failures). Detect the subscription **usage-cap** error
  distinctly — don't blind-retry it; if `ALLOW_METERED_FALLBACK` and key present, one failover
  call via `_chat_claude`; else raise `AIUsageCapError`.
- New exceptions: `AIChatError` (final transient failure), `AIUsageCapError`.
- `ai_chat_blocks()` gets the same route resolution.

### 3. `scripts/stage1_scrape.py` — kill the fabricated 50, add AI classification, retry queue

**Merged scoring contract** (Plan 2's shape, extended with Plan 1's fields):

| Case | `score` | `scored` | `sponsorship` | `company_type` |
|---|---|---|---|---|
| AI returned this URL | `int` | `True` | as classified | as classified |
| Batch succeeded, URL missing from output | `None` | `False` | `"unknown"` | `"unknown"` |
| Batch failed after retries | `None` | `False` | `"unknown"` | `"unknown"` |

- Extend the scoring prompt to also request `company_type: product | staffing_or_consulting |
  agency | unknown` (single combined call — do not add a second round-trip; see Conflict C4 notes
  below for why this matters to Step 7).
- Delete the blanket `except Exception → score 50` block. Call through the new retrying `ai_chat`.
  On final failure, return `None` for the whole batch and log loudly.
- `run()` branches on `s["scored"]`, **never** on `score == 50`.
- On unscored: write the job to Notion with an empty ATS score and `Status = "Retry"` (uses the
  status option added — and named — in this step; see Open questions). JD is already cached in the
  page body, so the retry costs **no Apify call**.
- New `rescore_retry_jobs(resume)`, called at the top of `run()` right after
  `ingest_interested_from_notion()`:
  1. `db_get_jobs(status="Retry")`.
  2. Read each JD back via `db_get_job_description(page_id)` (already exists).
  3. Re-score through the same `score_jobs_batch()`.
  4. Success → `db_update_status(page_id, "Scraped", {...})` with the real score. Failure →
     increment `Scoring Attempts`; once it exceeds `MAX_SCORING_ATTEMPTS`, promote to `Scraped`
     with an empty score and log `⚠ giving up on scoring after N attempts`.
- Apply Plan 1's drop logic, gated on `scored`:
  ```
  if s["scored"]:
      if EXCLUDE_NO_SPONSORSHIP and s["sponsorship"] == "no": drop, "no-sponsor/AI"
      if s["company_type"] in SKIP_COMPANY_TYPES:              drop, "staffing/AI"
  ```
  A failed/unscored batch must never be dropped on `company_type == "unknown"`.
- `ingest_interested_from_notion()`: on unscored, leave the page as `Retry` (don't promote to
  Scraped) — same self-match exclusion fix from Step 3 applies to `Retry` rows now that this status
  exists.
- Add `company_type` and `needs_review`/`retry` to the run counters and summary string.

### 4. `workflow.py` — batched scoring tool + resilient loop, and the enum gap

- New `score_jobs` jobpipe tool wrapping `stage1_scrape.score_jobs_batch(jobs, resume)` (fast tier
  → metered Haiku).
- Update `_task_morning`/`_task_scrape` prompts to score via one batched tool call instead of
  per-job in-context scoring.
- Move `os.environ.pop("ANTHROPIC_API_KEY")` to *after* the settings import, so settings captures
  the key for the metered fast tier while the SDK still authenticates via subscription.
- Wrap the streaming loop in try/except: on failure, report completed tool-call count and note
  re-running is safe (idempotent via Notion status + `check_job_in_db`).
- **Add the new status to `workflow.py:196 _STATUSES`.** This is a gap no source plan caught on
  its own — `_STATUSES` backs the `get_jobs`/status-update tool schema, so the agentic path cannot
  filter or set the new status until it's added here.

### 5. Decide Conflict C4 — `classify_company_type()` extraction

Plan 5 (Step 7) wants a standalone `classify_company_type(companies) -> dict` it can call with a
bare company name. This step's merged `score_jobs_batch()` keeps `company_type` welded to a prompt
that needs a résumé + JD (per Plan 1's explicit "keep it a single combined call" decision, §4).
Decide now:
- **(a)** extract a standalone version for Step 7 to reuse, accepting the extra round-trip cost, or
- **(b)** record that Step 7 falls back to `is_skipped_company()` alone and does not get AI
  company-type classification for leads.
Either is acceptable — just pick one and note it in this file's own history / commit message so
Step 7 doesn't re-litigate it.

## Acceptance criteria

- [ ] `python run.py --setup` prints the routing table (tier → provider/model), whether
      `ANTHROPIC_API_KEY` is present, and the current `Retry`-queue count.
- [ ] Temporarily point the fast tier at an invalid model, run `python run.py --stage 1` (one role,
      small `maxItems`): confirm 3 retries with backoff in the log, jobs land with an **empty**
      ATS score and the new `Retry` status (no `50`s anywhere), summary reads `0 scored / N queued
      for retry`.
- [ ] Restore the valid model, re-run: those same rows re-score **from the cached JD, no Apify
      call**, get real scores, flip to `Scraped`.
- [ ] Leave the invalid model in place for `MAX_SCORING_ATTEMPTS + 1` runs: `Scoring Attempts`
      increments each pass, job promotes to `Scraped` with an empty score and a `⚠ giving up` log
      rather than looping forever.
- [ ] A normal Stage-1 run logs the fast tier on metered Haiku; a Stage-2 tailor run logs the
      quality tier on subscription.
- [ ] Force a fake usage-cap error from `_chat_claude_code`: confirm a single metered failover with
      a warning, not 3 blind retries.
- [ ] `python workflow.py --task scrape`: agent calls `score_jobs` once per batch; turn count drops
      vs. before; interrupting mid-run prints completed-call count + re-run guidance.
- [ ] `workflow.py:196 _STATUSES` includes the new status; the agentic path can filter/set it.
- [ ] Live filtering check: a known staffing firm *not* in `SKIP_COMPANIES` gets caught by
      `[STAFFING/AI]` in the drop log; `Sponsorship` values appear on scraped Notion rows.

## Out of scope

- Cross-source fingerprint dedup — Step 6 (this step only fixes URL-based dedup's interaction with
  `Retry` rows, inherited from Step 3).
- Any Stage 2/3/5/6 call-site changes — they already pass `quality=` correctly and route
  automatically through the updated `ai_chat`.

## Open questions this must resolve before starting

- **Q1 (C3):** pick the status name (`Retry` recommended — it names the recovery mechanism, unlike
  `Needs Review` which describes a human action that doesn't happen automatically) and add it to
  the `Status` select in Step 2's migration if not already done, **and** to `workflow.py:196`.
- **Q3 (C4):** decide the `classify_company_type()` extraction question above.
- **Q7:** decide whether `Sponsorship = unknown` rows get a dedicated Notion view.

## Files touched

`config/settings.py`, `scripts/utils.py`, `scripts/stage1_scrape.py`, `workflow.py`, `run.py`
(`--setup` output only).

**Not touched:** Stages 2/3/5/6 call sites, filtering logic beyond what's listed above (Step 4's
pure functions already landed).

## References

- Architecture analysis §D.1 risk register R3 (🔴), R15 (🟡).
- `refinement-plans/README.md` Step 5 and Conflicts C1, C2, C3, C4.
- `refinement-plans/reliability/hybrid-agentic-migration-plan.md` — full spec, "Suggested order"
  and "Verification checklist" sections (items 1-8) map directly onto acceptance criteria above.
- `refinement-plans/filtering/stage1-filtering-rework.md` §3-9.
