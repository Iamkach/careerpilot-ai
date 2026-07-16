# Evals / testing strategy (Step 9)

## Problem

Steps 0-6 (scraping, scoring, tailoring, outreach, digest, interview prep, negotiation) plus
several reliability passes (Step 5's retry/typed-error work, Step 2's Notion writer hardening)
shipped entirely without automated tests. Confirmed by direct inspection of the repo:

- No `pytest` (or any test framework) in `requirements.txt`.
- No `conftest.py`, `pytest.ini`, `pyproject.toml`, or `tox.ini` anywhere.
- No `tests/` directory.
- No `on: pull_request` or `on: push` CI trigger anywhere. The only workflow,
  `.github/workflows/nightly-pipeline.yml`, is the live production cron job itself (plus a
  `workflow_dispatch` manual-run variant) — its only "verification" step is
  `python run.py --setup`, a config/API-key sanity check, not a test.

Every change so far has landed by manual spot-checks against the real Notion DB and real AI
calls. There is currently zero automated gate before code reaches `main`.

## Approach

Phased, cheapest/highest-leverage first. Phases 0-4 are pure regression-safety infrastructure —
deterministic, mocked, free, and gated in CI. Phase 5 is a separate, opt-in AI-quality layer that
intentionally is *not* part of CI (it costs money and is inherently non-deterministic).

Decision already made: **mock AI calls in CI** (`ai_chat`/`ai_chat_blocks` monkeypatched to
canned responses) rather than hitting the real Anthropic API on every PR — fast, free,
deterministic, no flakiness, no `ANTHROPIC_API_KEY` needed in the PR-gate workflow. A separate
opt-in script (Phase 5) hits the real API for periodic quality checks only.

### Phase 0 — Harness setup (Size: S, depends on: none)

- New `requirements-dev.txt` at repo root: `pytest`, `pytest-mock`. Keeps the prod
  `requirements.txt` untouched, matching how this repo already separates optional provider deps
  with comments.
- New `tests/` directory with `conftest.py` providing:
  - A fake `ai_chat`/`ai_chat_blocks` fixture — returns caller-supplied canned strings instead of
    calling the real backend.
  - A fake Notion layer — `db_find_job_by_url`, `db_add_job`, `db_update_status`, `db_get_jobs`,
    `db_get_all_jobs`, etc. (`scripts/utils.py`) monkeypatched to operate on an in-memory dict
    instead of the real Notion API.
  - A sample resume text fixture and a handful of sample job dicts (title/company/description)
    reused across Phase 1-3 tests.
- New `.github/workflows/tests.yml` on `pull_request` + `push`, **separate** from
  `nightly-pipeline.yml` (which stays exactly what it is today — the live-prod cron job). This
  directly closes the "zero automated gate before `main`" gap.

### Phase 1 — Unit tests for pure functions (Size: S, depends on: Phase 0)

Highest value per hour: no mocking required, exact inputs → exact outputs, and the codebase
already has a lot of hand-verified logic worth locking in before the next refactor silently
breaks it.

Targets:

- **`scripts/sources.py`**
  - `job_fingerprint` / `_norm_company` / `_norm_title` — legal-suffix stripping (`"Stripe, Inc."`
    → `"stripe"`), roman-numeral mapping (`i..viii` → digits), dash/parenthetical/req-number
    stripping in titles, and the "seniority words are kept, not stripped" behavior.
  - `collapse_by_fingerprint` — source-priority collapsing (`greenhouse=0 < lever=1 < ashby=2 <
    linkedin=3 < default=5 < indeed=8`, lower wins), order-independence of the input list.
  - `title_matches_targets` — all-tokens-present, order-independent substring match.
  - `_is_fresh` — `None` posted_date treated as fresh unless `DROP_UNDATED_JOBS`; boundary at
    exactly `MAX_JOB_AGE_DAYS`.
  - `_to_iso_date` — epoch ms/s, ISO strings with `Z`, bare dates, digit-strings.
  - `_parse_salary`.
- **`scripts/utils.py`**
  - `matches_company_list` / `_tokens` / `_strip_suffix` / `_subseq` — word-boundary company
    matching; the `"UST"` vs `"Customer.io"` false-positive case the docstring explicitly calls
    out, plus `"Tata Consultancy"` matching `"Tata Consultancy Services"`.
  - `parse_json_response` — **the single highest-leverage test target in the repo**, since nearly
    every AI-parsing path in every stage depends on it. Cases: fenced ` ```json ` blocks, prose-
    wrapped JSON, malformed/truncated JSON, JSON objects vs. arrays, embedded braces inside
    string values, empty-string input.
- **`scripts/stage2_tailor.py`**
  - `_sponsorship_gate` — matched-company + marker-absent (held back), matched-company +
    marker-present (released), unmatched company (untouched); mock `db_update_status` and assert
    the note-append formatting in both the empty-notes and pre-existing-notes cases.
- **`scripts/stage6_negotiate.py`**
  - `get_company_type` — trivial hardcoded-list exact-match function, cheap to lock in.
- **Markdown → HTML regex converters** — `stage5_interview_prep.render_html` and
  `stage6_negotiate.render_brief` are pure and AI-independent. Test `## `/`### ` → `<h2>`/`<h3>`,
  `* `/`- ` → `<li>`, `**bold**` → `<strong>`, paragraph-break handling. Also add a
  **characterization test** (not a fix) documenting the known gap that consecutive `<li>` lines
  are never wrapped in `<ul>`/`<ol>`, producing invalid list HTML today — the test locks in
  current behavior and gives future-you a single place to update when it's actually fixed.

### Phase 2 — Golden-file tests for docx handling (Size: S, depends on: Phase 0)

`scripts/render_docx.py`'s `extract_docx_text` / `apply_docx_edits` are fully deterministic — no
AI call happens in this module; the AI only produces the `{old, new}` edit list upstream in
stage 2. This makes it a strong golden-file/snapshot-testing candidate.

- Add a small fixture `.docx` under `tests/fixtures/`.
- `extract_docx_text` — assert exact extracted text against the fixture.
- `apply_docx_edits` — assert exact post-edit text for a fixed edits list; assert the
  **unmatched-edit return value** (edits whose `old` matched no paragraph are collected, not
  silently dropped) for an edit that doesn't appear in the fixture.
- Two explicit **characterization tests** for known edge cases surfaced during the codebase
  audit, so they're documented rather than silently relied upon:
  - Run-collapsing: a partial-paragraph edit collapses all runs in that paragraph into the first
    run's style, which loses run-level formatting (e.g. bold/italic) on the rest of the paragraph.
  - Same-paragraph double-edit: two edits whose `old` text overlaps within the same paragraph can
    clobber each other, since only the *first* occurrence of each `old` is replaced.

### Phase 3 — Mocked AI-flow contract tests (Size: M, depends on: Phase 0)

With `ai_chat`/`ai_chat_blocks` monkeypatched to return fixed canned JSON/text, test the
**plumbing** around each AI call — not whether the AI's judgment is good (that's Phase 5), but
whether the code correctly handles what the AI could plausibly (or implausibly) return.

- **`stage1_scrape.score_jobs_batch`**
  - Happy path: well-formed batch response → correct per-job dicts.
  - A job URL missing from the AI's returned array → that job falls back to `_unscored()`
    (`score: None, scored: False, sponsorship: "unknown", company_type: "unknown"`), not a
    fabricated score.
  - The whole call raising `AIChatError` (exhausted retries) → every job in the batch comes back
    `_unscored()`.
  - Invalid `sponsorship`/`company_type` enum values from the model → coerced to `"unknown"`.
  - **Documented known gap, not fixed here:** `score` is coerced via `int(entry.get("score", 0))`
    with no bounds clamping — a hallucinated score of `150` or `-10` passes through uncaught. Add
    a test asserting *today's* (unclamped) behavior, with a comment flagging it as a real bug
    candidate for a future fix, not this pass.
- **`stage1_scrape.rescore_retry_jobs`** — the give-up boundary: at `MAX_SCORING_ATTEMPTS` (3)
  failed attempts the job stays `Retry`; at `MAX_SCORING_ATTEMPTS + 1` it force-promotes to
  `Scraped` with a permanently empty score.
- **`stage2_tailor.tailor_resumes_batch` / `_tailor_resume_single`**
  - Batch-to-per-job fallback: a malformed batch response returns `{}`, and every job falls back
    to the single-job path.
  - Result keying by 1-based `job_index` with `by_company` as the secondary lookup.
- **`stage2_tailor.verify_tailored_score`** — an empty result list from `score_jobs_batch`
  synthesizes `{"url": ..., "score": None, "scored": False}` rather than raising.
- **`stage3_outreach`**
  - InMail truncation: `subject[:200]`, `body[:1900]` — exact boundary behavior at 199/200/201
    and 1899/1900/1901 chars.
  - **Documented known inconsistency, not fixed here:** the cold-email single-job fallback
    (`_draft_cold_email_single`) does ad-hoc `raw.strip().strip("```json").strip("```")` instead
    of reusing `parse_json_response`, unlike every other AI-parsing path in the codebase. A test
    locks in today's behavior; the inconsistency itself is a candidate for a future cleanup.

### Phase 4 — CI gate live (Size: XS, depends on: Phases 0-3)

`tests.yml` runs `pytest` on every PR/push using only the Phase 0 mocks — no
`ANTHROPIC_API_KEY`, `NOTION_API_KEY`, or `APIFY_API_TOKEN` required or used anywhere in the
suite, so the workflow is free to run and has no external dependency to flake on. This is the
concrete, mechanical fix for "no automated gate before `main`."

### Phase 5 — AI-quality eval layer (Size: M, depends on: Phases 0-4, harness reused; NOT part of CI)

A separate, opt-in layer for tracking whether the AI's actual *judgment* is good — something
mocked contract tests cannot see by construction, since they assert against canned responses.

- A small hand-labeled dataset (`tests/eval_data/` or a top-level `evals/` directory): 8-12 real
  job descriptions + the resume, each with a human-assigned expected ATS score range and expected
  missing-keywords set.
- A standalone script, e.g. `scripts/run_evals.py`, deliberately **outside** `run.py`'s pipeline
  entry point so it can never be invoked by the nightly workflow or `--evaluate` by accident. It
  hits the **real** Anthropic API against the labeled dataset and reports:
  - Score-vs-expected-range hit rate (stage 1 scoring).
  - Keyword-recall against the labeled missing-keywords set.
  - Tailored-resume ATS delta (before → after, stage 2), reusing `verify_tailored_score`'s
    contract.
- Not gated in CI. Run manually before/after a prompt or model change (e.g. swapping
  `QUALITY_MODEL`, editing a stage's system prompt) to catch quality drift that Phase 3's mocked
  contract tests are structurally incapable of catching.
- Also the natural home for periodically re-validating stage 6's comp-benchmark prompt. The
  codebase audit for this plan flagged that `generate_negotiation_brief`'s prose asks the model to
  reference levels.fyi/Glassdoor/Blind from its own training knowledge — despite the module
  docstring's claim of "Claude + web search," there is no actual web-search tool call in the code.
  That's a real factual-accuracy/staleness risk worth a recurring **manual** eval check, not a
  blocking automated one (comp data changes over time in a way no fixed test oracle can track).

## Sizing summary

| Phase | Size | Depends on |
|---|---|---|
| 0 — harness + CI wiring | S | none |
| 1 — pure-function unit tests | S | Phase 0 |
| 2 — docx golden-file tests | S | Phase 0 |
| 3 — mocked AI-flow contract tests | M | Phase 0 |
| 4 — CI gate live | XS | Phases 0-3 |
| 5 — AI-quality eval dataset + script | M | Phases 0-4 |

Total story size: **M-L**. No blocking dependency on Step 7 or Step 8 — can start immediately.

## Non-goals

- Not fixing the bugs/inconsistencies this audit surfaced (unclamped ATS score, cold-email JSON-
  parsing inconsistency, missing `<ul>` wrapping in the markdown→HTML converters, stage 6's
  no-actual-web-search prompt). Phases 1-3 deliberately write **characterization tests** that lock
  in current behavior and flag these as documented gaps — fixing them is separate future work,
  tracked as a note in `docs/TODO.md` alongside this story rather than folded into it.
- Not adding real-API integration tests to CI. Phase 5's live-API script is opt-in/manual by
  design; a metered API call on every PR is a cost and reliability trade-off this plan explicitly
  avoids.
- Not testing `scripts/spike_phase0_leads.py` (Step 7 Phase 0 spike, not part of the shipped
  6-stage pipeline) or `render_docx.render_resume_docx`/`normalize_resume_data` (the legacy
  Jinja2/`docxtpl` template path, superseded by `apply_docx_edits` and not used by the current
  `stage2_tailor.py` flow — confirm it's genuinely dead before ever investing test effort there).
