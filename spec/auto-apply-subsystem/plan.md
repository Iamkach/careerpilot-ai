# Plan

## Proposed architecture — a capability router (not a single scraper)

Mirror `sources.py`'s registry pattern. One dispatcher keyed on source/domain, one *adapter* per
class, each returning the same result shape so the runner and Notion mapping stay uniform.

```
Reviewed + Resume Tailored job
        │
        ▼
  detect_apply_channel(job)            # url domain → 'greenhouse'|'lever'|'ashby'|'workday'|'linkedin'|...
        │
        ▼
  build_application_plan(job, profile) # map every known/needed field → value; flag unanswerable
        │                              #   - deterministic from APPLICATION_PROFILE (name, email, work-auth…)
        │                              #   - LLM-drafted for free-text (cover-letter-style), marked review_required
        │                              #   - resume = Stage 2 tailored .docx (→ PDF if the form demands)
        ▼
  ADAPTER[channel].apply(job, plan, mode)
        │   mode = plan | fill | submit
        ├─ greenhouse_adapter   (browser fill, schema-driven)
        ├─ lever_adapter        (browser fill)
        ├─ ashby_adapter        (browser fill, expect captcha)
        ├─ workday_adapter      (agentic, account-aware)
        └─ manual_adapter       (LinkedIn/Indeed/unknown → emit answer sheet, no submit)
        │
        ▼
  map result → Notion status
```

Three execution *substrates*, used by tier, not one-size-fits-all:

- **Schema-driven browser fill** (Playwright + Greenhouse `questions` schema) — deterministic,
  fast, cheapest to run; best where the field schema is knowable (Greenhouse). Brittle to markup
  changes, so gate on "did the expected fields resolve?"
- **Agentic browser driver** (Claude-in-Chrome / computer-use) — self-locates fields, handles
  novel/multi-page forms (Workday), reads the page to decide. Slower, costs model calls, but
  survives selector drift and is the only realistic path for the long tail. Pauses for the human
  on captcha/auth by design.
- **No-automation handoff** (manual_adapter) — for ToS-prohibited or unknown targets: produce a
  filled-in answer sheet (every question + the answer we'd give + the resume path + a deep link)
  so the human applies in <60s without re-deriving anything.

## Phased plan

**Phase 0 — spike (blocking, done).** Confirmed against real Greenhouse-hosted jobs: schema fetch
works end-to-end, captcha behavior on submit, browser substrate choice (Playwright).

**Phase 1 — read + plan, zero submit. SHIPPED.** `scripts/autoapply.py`: detect channel, fetch the
Greenhouse `questions` schema, build the application plan from `APPLICATION_PROFILE` + tailored
resume, emit a readiness report, write `Application Queued` / `Needs Human: Question` to Notion.
No browser, no submit.

**Phase 2 — semi-auto browser fill for Greenhouse + Lever. SHIPPED.** Playwright fills the hosted
form from the Phase-1 plan, uploads the resume, stops before submit, screenshots for the human.

**Phase 3 — deliberate submit + Ashby. OPEN, deferred by choice.** `--submit` behind a daily cap;
handle Ashby's captcha as a clean handoff. Trigger to pick this up: real usage data from the fill
path, not a calendar date — the research argues ATSes score application velocity, so rushing the
final click has lower marginal value than it looks.

**Phase 4 — agentic long tail (Workday/custom) via Playwright. OPEN, not started.** Claude-in-Chrome
driver, account-aware, always human-confirm. Highest maintenance; last for a reason, and the
interactive case is now covered by `spec/application-prefill-extension/` instead — this phase only
matters for an unattended run.

**Never:** automated submit on LinkedIn/Indeed. `manual_adapter` answer sheet only.

## Landed (Phases 1-2) — component map

| Component | File |
|---|---|
| Layer 1 — routing, schema read, answer resolution, gating, answer sheet, Notion writes | `scripts/autoapply.py` |
| Layer 2 — Playwright pre-fill, no submit path | `scripts/autoapply_browser.py` |
| Profile + preset banks + cap | `config/settings.py` |
| Verified status write, new property converters | `scripts/utils.py` |
| Stage dispatch + sampling flags | `run.py` (`--stage 7`, `--fill`, `--dry-run`, `--limit`, `--setup-profile`) |
| One-time answer wizard (git-ignored `config/application_profile.json` overlay) | `scripts/autoapply_profile.py` |
| One-time, idempotent Notion schema migration (6 Status options + 4 properties) | `scripts/setup_notion_schema.py` |
| Tests | `tests/test_autoapply_{plan,notion,browser,profile}.py`, `tests/test_setup_notion_schema.py` |

**Ergonomics that landed after the core:** `--setup-profile` captures application answers once
into a git-ignored JSON overlay instead of editing `config/settings.py` per change; `--dry-run`
(+ `--limit N`) samples the stage on real jobs — real answer sheets, zero Notion writes, no
browser — so output can be eyeballed before committing to the live path.

## Fixed since initial landing (address/attachment mapping, 2026-07-21)

Live schema fetch validated once against a real tracker job (SmithRx). Surfaced and fixed two
mapping gaps: (a) the structured-address block is now captured by a new `"address"` section in
`run.py --setup-profile`, persisted to `config/application_profile.json`, exposed as
`APPLICATION_ADDRESS`, matched via new `_LABEL_RULES` keyword entries (label text, not field
`name` — Greenhouse's `name` attributes for these fields are opaque); (b) the dual-field
attachment quirk (an `input_file` + a `textarea` under one label) is fixed in
`build_application_plan()` — the `textarea` sibling of an already-resolved attachment field now
mirrors that field's resolution instead of being independently evaluated. Covered by
`tests/test_autoapply_profile.py` and `tests/test_autoapply_plan.py`.

## docx→PDF conversion — closed (2026-07-21)

`scripts/render_docx.py` gained `convert_docx_to_pdf()`, shelling out to headless LibreOffice
(`soffice --headless --convert-to pdf`). `autoapply_browser.py`'s `_resolve_upload_path()` calls
it only when the form's file input rejects `.docx`; degrades to the original `pdf_only` stop if
LibreOffice isn't installed or conversion fails (never raises). Unit-tested with a mocked
`subprocess.run`; untested against a live PDF-only form (none seen yet in the tracker).

## Files

- **Existing (Phases 1-2, no further change expected unless Phase 3/4 work requires it):**
  `scripts/autoapply.py`, `scripts/autoapply_browser.py`, `scripts/autoapply_profile.py`,
  `scripts/setup_notion_schema.py`, `config/settings.py` (profile/presets/cap),
  `scripts/render_docx.py` (`convert_docx_to_pdf()`).
- **New, when Phase 3 starts:** `--submit --yes-i-mean-it` flag wiring in `scripts/autoapply.py`/
  `scripts/autoapply_browser.py`; a submit-attempt daily cap distinct from the existing
  fill/plan cap; Ashby captcha-handoff handling.
- **New, when Phase 4 starts (if the unattended-run case is ever prioritized):** an agentic
  Workday/custom-site driver module, account-provisioning credential handling — likely its own
  new file given the different execution substrate (Claude-in-Chrome vs. Playwright).
