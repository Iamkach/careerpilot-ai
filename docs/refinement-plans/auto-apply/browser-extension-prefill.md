# Browser extension for application pre-fill — a Layer 3 beside the Playwright fill

*See [`../README.md`](../README.md) for how this plan relates to the others.*

**Status (2026-07-26): not started, not queued.** Written down after a user question ("can we
create a browser plugin that pre-fills job applications?") during Step 10 follow-up. This is the
same idea already named as **Option C** in
[`ashby-workday-custom-fill.md`](ashby-workday-custom-fill.md) ("a browser extension"), but that
doc treated it as a *consolation prize* — improve the answer sheet since a real fill is expensive.
This doc argues the opposite: an extension is a **better** substrate than either Playwright
adapter option there, because reading the live DOM removes the per-ATS schema/selector problem
that makes Options A and B expensive in the first place. Design decisions below are settled;
scheduling is not. **The two docs are complementary — neither supersedes the other yet.**

## Current behavior (as shipped, Phases 1–2)

`FILLABLE_CHANNELS = {"greenhouse", "lever"}` (`scripts/autoapply.py:106`) gates Layer 2. Ashby,
Workday, and every company's own careers page (`unknown`) get full Layer 1 treatment — routing,
field resolution, Notion write, HTML answer sheet — but no browser is ever opened. You re-type the
answer sheet by hand. That hand-typing is the bottleneck this plan removes.

## Why an extension beats the Playwright options

`ashby-workday-custom-fill.md`'s Options A and B are both expensive for the same underlying
reason: Playwright drives a *fresh, anonymous* browser, so it needs to know each ATS's field
schema ahead of time (Option A: probe Ashby's API, may not exist) or reason its way around one
per-page at model cost (Option B: agentic driver). An extension runs inside **your already-open,
already-authenticated session**, so:

- **The live DOM is the schema.** No per-ATS schema API, no per-ATS selector adapter. Ashby,
  Workday and arbitrary custom forms are one code path. This is the whole argument.
- **Workday's real cost disappears.** That doc calls per-company tenant accounts "the real cost,
  not selector work" — you're already logged in, so there is nothing to provision.
- **Better than `GENERIC_QUESTIONS`.** Non-Greenhouse channels currently plan against a 6-field
  guess with `schema_known=False`. The live form is ground truth about what it actually asks.
- **No captcha/auth handling needed.** The two failure modes `autoapply_browser.py` spends
  `_classify_block()` on can't occur — a human is already past them.

Cost, honestly: a second UI surface to maintain, an HTTP bridge that serves personal data to a
browser (see Security), and it is **interactive only** — it does nothing for an unattended run,
so it complements the Playwright layer rather than replacing it.

## Trigger criteria — when to actually pick this up

Same gate as `ashby-workday-custom-fill.md`, since it addresses the same bottleneck: **enough
real Ashby/Workday/custom-domain `Resume Tailored` rows that hand-typing the answer sheet is the
actual daily bottleneck.** Per `docs/TODO.md`, the tracker is still 413 LinkedIn / 90 Indeed / 4
unknown of 508 — so shifting `ENABLED_SOURCES` weight toward ATS boards remains a prerequisite
this hasn't hit. One addition: if apply volume rises on *Greenhouse* too, that alone can justify
this, since the extension is faster than `--stage 7 --fill` even where Playwright already works
(no headless launch, no drift guard, you see it happen).

## Design decisions (settled)

| Decision | Choice | Why |
|---|---|---|
| Architecture | **Local Python bridge**, extension is a thin DOM client | All answer logic stays in `autoapply.py`; nothing ported to JS, so nothing can drift |
| Fill behavior | Fill `ready` fields on **click**, badge the rest | Never auto-runs on load — a wrong eligibility answer is unretractable |
| Scope | Every form **except LinkedIn/Indeed**, which stay read-only overlay | Preserves the existing permanent rule |
| Distribution | Unpacked/developer-mode only | A store listing for something that reads application forms is a different review problem |

### Architecture

The load-bearing idea: the content script scrapes the DOM into the **exact schema shape
`build_application_plan()` already consumes**, so the answer-resolution layer is reused verbatim.

```
┌─ Chrome ────────────────────────┐        ┌─ localhost:8765 ──────────────┐
│ content.js                      │        │ scripts/autoapply_server.py   │
│  1. scrape form → questions[]   │──POST /plan──▶ build_application_plan()│
│     {label, required,           │        │      readiness_report()       │
│      fields:[{name,type}]}      │◀─plan JSON─── (autoapply.py, unchanged)│
│  2. fill status=="ready"        │        │                               │
│  3. badge review_required       │──GET /resume──▶ tailored .docx bytes   │
│  4. never touches submit        │        │                               │
└─────────────────────────────────┘        └───────────────────────────────┘
```

**Forward-looking note (2026-07-26, not implemented — this doc's status is unchanged):** by the
time this gets built, `resolve_tailored_resume()` (`scripts/autoapply.py`) will already handle two
link schemes for `Tailored Resume Link` — a local `file://` path, and a `raw.githubusercontent.com`
URL for a job whose resume was tailored on the nightly CI runner (see `docs/TODO.md`'s "Nightly
output retrieval" entry). `GET /resume` should reuse `resolve_tailored_resume()` rather than
assuming a local file, so the extension also works for a CI-tailored job with no `.docx` on this
machine.

For Greenhouse the bridge still *prefers* the authoritative `fetch_greenhouse_questions()`
(`autoapply.py:163`) and falls back to the scraped DOM, so today's Greenhouse behavior is strictly
preserved. Elsewhere the scraped DOM is the schema, with `schema_known=True`.

### Which job am I on? (`identify_job()`)

The extension must map the page to a Notion row to pick the right tailored resume — and the apply
URL is routinely *not* the URL stored in Notion (`job-boards.` vs `boards.` hosts, `?gh_src=`
params, an `/apply` subpage, a careers-page redirect). Ladder, all helpers already existing:

| # | Match | Helper | Confidence |
|---|---|---|---|
| 1 | Exact Job URL | `db_find_job_by_url()` (`utils.py:819`) | exact |
| 2 | Normalized URL (drop query/fragment, strip `/apply`, fold `job-boards.`→`boards.`) | `db_get_all_jobs()` (`utils.py:954`) | high |
| 3 | Greenhouse `(board_token, job_id)` equality | `parse_greenhouse_url()` (`autoapply.py:125`) | high |
| 4 | `job_fingerprint(company, title)` from the page vs. all rows | `job_fingerprint()` (`sources.py:713`) | medium |
| 5 | no unique hit → **ask** | popup lists `Resume Tailored` rows | human |

Page company/title for rung 4 come from JSON-LD `JobPosting` if present (the signal
`generic_url_fetch()` already prefers), else `og:title`/`<h1>` + host.

**Ambiguity is never resolved by guessing** — two rung-4 hits or zero falls to rung 5. Attaching
the wrong company's tailored resume to a real application is unretractable, the same error class
the eligibility rule already refuses to risk. The popup always shows what matched and how
("Acme — Senior PM · matched by URL") so a bad match is visible *before* filling.

**No match is a supported state, not an error:** the resume field resolves `review_required` —
`_resolve_field()` already does exactly this for an empty `resume_path` (`autoapply.py:286-289`,
source `"resume-missing"`), so no new branch. Every other field still fills, which means the
extension also works on a job you found yourself that was never scraped.

### Invariants to preserve

- **No submit path anywhere** — no submit-control `.click()`, no `form.submit()`, no Enter key.
  `tests/test_autoapply_notion.py:66-73` already greps `autoapply_browser.py` for this; extend
  the grep to `extension/content.js`.
- **Never writes `Applied`** — bridge exposes only `WRITABLE_STATUSES` (`autoapply.py:76`).
- **Eligibility never guessed** — free, since `_resolve_field()` remains the only resolver.
- **LinkedIn/Indeed never filled** — enforce **server-side** in the bridge (channel in a
  `_READONLY_CHANNELS` set → all fields returned `review_required`), not just in JS, so a bug or
  a hand-edited content script can't bypass it. Leave `FILLABLE_CHANNELS` untouched; it governs
  the Playwright layer and should keep meaning exactly what it says.

### Security

The bridge serves your profile and resume to a browser. Non-negotiable: bind `127.0.0.1` only; a
random token (git-ignored `config/extension_token.txt`) checked on every request; CORS echoed only
for job-site origins; runs **only** while you explicitly `python run.py --serve`, never a daemon.

## Recommended sequencing (when triggered)

1. **Bridge + `identify_job()` + tests** — verifiable with `curl` alone, before any extension code
   exists. Useful on its own as a machine-readable planning endpoint.
2. **Extension read-only** — scrape, `POST /plan`, badge/overlay, popup match display + job
   picker. No field writes. This is already faster than the HTML answer sheet.
3. **Fill** — write `ready` fields on click; resume upload via `DataTransfer` from `GET /resume`.
4. **Docs** — CLAUDE.md section, and *then* reconcile with
   [`ashby-workday-custom-fill.md`](ashby-workday-custom-fill.md): if this ships, that doc's
   Options A and B are moot and it should be deleted as part of the same change (its Option C
   becomes this). Do not delete it before then.

## Files (when implemented)

- **New:** `scripts/autoapply_server.py` — stdlib `http.server` (no new dependency; the repo has
  no HTTP layer today and shouldn't gain Flask for this). Routes `POST /plan`, `GET /resume`,
  `POST /status`, `GET /health`. Imports the planner from `scripts/autoapply.py`,
  `job_fingerprint` from `scripts/sources.py`, `db_*` readers from `scripts/utils.py`. Holds
  `identify_job()` but **zero** answer logic of its own.
- **New:** `extension/` — `manifest.json` (MV3, `host_permissions` for `127.0.0.1:8765` + job
  domains, `activeTab`-gated so it doesn't run on every site), `content.js` (scraper + filler;
  fills must dispatch `input`/`change` since React-controlled forms ignore a bare `.value` write),
  `overlay.css`, `popup.*`, `options.*`.
- **Modify:** `run.py` — `--serve [--port N]`, following the `--setup-profile` dispatch pattern.
- **Modify:** `CLAUDE.md` (a "Layer 3 — browser extension" subsection under Stage 7),
  `.gitignore` (`config/extension_token.txt`).

## Verification (when implemented)

1. `pytest -v` green. New `tests/test_autoapply_server.py` (a scraped-DOM payload yields the same
   plan as the equivalent schema; a linkedin.com URL returns all fields `review_required`
   regardless of profile completeness; bad token rejected; `POST /status` refuses `"Applied"`;
   `GET /resume` refuses a path outside the resume dir) and
   `tests/test_autoapply_job_match.py` (one case per rung against `FakeNotionDB`, plus **two
   fingerprint candidates → `ambiguous`, picks neither** and **no candidate → resume
   `review_required` while other fields still resolve**). `pytest -m browser` unaffected.
2. Feed `SAMPLE_QUESTIONS` (`autoapply.py:189`) through `POST /plan` and diff against
   `python scripts/autoapply.py --sample --json` — identical output is the proof the bridge adds
   no logic.
3. Live, **on forms you do not intend to submit**: Greenhouse (must match the CLI plan) → Ashby →
   a custom careers page (the actual new capability).
4. Job match: open a real `Resume Tailored` job's apply form, confirm the popup names the right
   role and attaches that job's `.docx`; re-open with `?gh_src=test` and via the `job-boards.`
   host — both must still match; then open an untracked job and confirm it fills everything else
   and leaves the resume badged rather than attaching another job's resume.
5. LinkedIn Easy Apply: confirm **nothing** is filled.
6. Confirm the page's Submit button is untouched and no POST leaves the page until you click it.
