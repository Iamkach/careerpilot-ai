# TODO — reliability, filtering, tailoring quality, networking sourcing

Reworked from `plan/reliability-filtering-networking.md`. Changes from the first draft:
decisions are resolved up front instead of buried in tasks; references use symbol names
(line numbers rot); every default change carries its doc-update task; §Networking is gated
behind its research spike instead of pre-listing buildable checkboxes; and a new section
covers ATS tailoring verification, which the plan didn't address but is the pipeline's
core quality gap.

---

## 0. Decisions (resolved — implement, don't re-litigate)

**AI implementation = hybrid:**
- **Unattended/scheduled runs** (`run.py` stages, daily cron): metered API
  (`STAGE_AI_PROVIDER = "claude"`). Single-shot JSON calls, batched where inputs share a
  cacheable prefix, retry-with-backoff. No usage-cap exposure, prompt caching works.
- **Interactive/ad hoc runs** (`workflow.py` agentic loop): stays on `claude_code`
  subscription — waiting out a cap at the keyboard costs nothing, and the agentic loop's
  flexibility is worth it when a human is watching.
- Invariant: no cron-runnable code path may drive an agentic loop (`query()` with
  `max_turns > 1`).

**Networking sourcing (§4)** ships nothing until the actor research spike passes.

---

## 1. AI-call reliability

### Provider split (per decision 0)
- [ ] Set `STAGE_AI_PROVIDER = "claude"` in `config/settings.py`; leave `AI_PROVIDER =
      "claude_code"` for `workflow.py`
- [ ] Confirm every `_chat_*` dispatch in `scripts/utils.py` honors `STAGE_AI_PROVIDER`
      (the plumbing exists; verify with a forced-provider smoke run of stage 3)
- [ ] **Docs**: update CLAUDE.md provider table, "Key Design Patterns", and the
      `claude_code` caveats paragraph — all three currently state the old single default.
      Same commit as the settings change.

### Retry / backoff (transient only)
- [ ] Add one shared `retry_ai(fn, attempts=3, backoff=(2,4,8))` helper in
      `scripts/utils.py`; wrap the body of each `_chat_*` backend with it
- [ ] Retry on: rate limit, 5xx, timeout. **Never** retry usage-cap-exceeded — detect it
      distinctly and exit with "subscription cap hit; wait for renewal, then re-run
      (completed jobs are skipped)"
- [ ] Wrap `workflow.py::_run()`'s `query()` loop in try/except: on failure print
      tool-calls completed so far + the safe-to-re-run message (lean on existing Notion
      status idempotency — no checkpoint file)
- [ ] Same try/except + message around `score_jobs_batch()` in `stage1_scrape.py` and the
      InMail/outreach calls in `stage3_outreach.py`

### Verify
- [ ] Force a transient error (temporarily invalid model name) → retry engages, message
      distinguishes cap vs transient
- [ ] Kill a run mid-way, re-run → already-processed jobs skipped

## 2. ATS tailoring — make it verifiable (new; highest quality-impact)

Today `apply_docx_edits()` (`scripts/render_docx.py`) silently drops any edit whose `old`
string doesn't match a paragraph verbatim, the batch path truncates JDs to 2000 chars while
the single-job fallback uses 8000, and nothing re-scores after tailoring — so stage 2 can
no-op and still log success.

- [ ] **Pre-validate edits**: check every `old` against `extract_docx_text()` output before
      touching the docx; if any miss, retry the AI call once with the closest-matching
      paragraph quoted back as the required anchor
- [ ] **Normalize matching**: NFKC + collapse whitespace + straighten quotes/dashes when
      locating `old` in paragraph text; apply the replacement to the original run text
- [ ] **Count applied vs skipped** in `apply_docx_edits()` (return counts; log a ⚠ per
      skipped edit in stage 2 output — silence is the bug)
- [ ] **Post-verify**: re-extract the saved docx, assert each `new` is present; fail loudly
      otherwise
- [ ] **Re-score**: run the stage-1 ATS scorer on (tailored text, JD); write
      `ats_score_after` to Notion (new number property) — the before/after delta is the
      stage's success metric
- [ ] **Unify JD length** between `tailor_resumes_batch()` and `_tailor_resume_single()` so
      the fallback is a retry, not a different experiment
- [ ] Verify: tailor one job with a deliberately stale `old` edit → run reports the skip,
      retry repairs it, `ats_score_after` lands in Notion

## 3. Filtering — product companies, sponsorship visibility

- [ ] Extend `score_jobs_batch()` response schema with
      `company_type: product | staffing_or_consulting | agency | unknown` (same batched
      call, no extra API cost); drop `staffing_or_consulting` mirroring the existing
      `sponsorship == "no"` drop; log via existing `_log_drop()`
- [ ] Remove `"Qualcomm"` from `SKIP_COMPANIES` (false positive); spot-check the list for
      similar real product companies while in the file
- [ ] Write the `sponsorship` classification (+ short reason) to a Notion property so
      `"unknown"` rows are visible instead of silently passed
- [ ] Add `SPONSORSHIP_MODE = "lenient" | "strict"` to settings (`strict` also drops
      `"unknown"`); default `lenient`
- [ ] Delete or wire up `TARGET_COMPANIES` (currently dead config in settings.py)
- [ ] **Docs**: document `SPONSORSHIP_MODE` and the company-type filter in CLAUDE.md
      "Stage 1 Filters"
- [ ] Verify: small `--stage 1` run → a staffing firm *not* in `SKIP_COMPANIES` is caught
      by `company_type`, Qualcomm survives, `unknown`-sponsorship rows visible in Notion

## 4. Networking sourcing — GATED

- [ ] **Gate: research spike.** Find and validate an Apify actor for LinkedIn post/people
      search: pricing, output schema, ToS exposure, rate limits. Write findings to
      `plan/networking-actor-spike.md` with a go/no-go recommendation.

Everything below is **frozen until the spike says go** (design already sketched in
`plan/reliability-filtering-networking.md` §3 — don't duplicate it here):
`stage7_network_sourcing.py` on the `_apify_run()` pattern · regex→LLM poster-role
classification · reuse §3 company-type filter · separate Notion Leads DB
(`Identified → Approved → Messaged → Replied → Connected`) ·
`draft_connection_request()` in stage 3 for `Approved` leads only, drafts to
`output/outreach/`, never auto-send.

Non-negotiables carried from the plan: manual approval gate before any draft; human sends
manually; aggressive rate limiting; treat as experimental.

---

## Order of work

1. §1 reliability (unblocks safe unattended runs — the failure that cost real time)
2. §2 tailoring verification (core product quality; currently unfalsifiable)
3. §3 filtering (quality of what enters the pipeline)
4. §4 spike only; build iff go

One commit per section; each commit includes its doc updates and its verification step run.
