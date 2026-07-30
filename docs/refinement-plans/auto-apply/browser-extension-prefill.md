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

**Corrected 2026-07-29 — the old trigger measured the wrong host.** It read "enough real
Ashby/Workday/custom-domain `Resume Tailored` rows that hand-typing the answer sheet is the
actual daily bottleneck", counted against the tracker's 413 LinkedIn / 90 Indeed / 4 unknown /
1 Greenhouse of 508. That count is of **posting** hosts. What decides fillability is the
**apply-form** host, and the two are routinely different — a LinkedIn posting whose Apply button
bounces to a company's Greenhouse form is an application the already-shipped Layer 2 could fill
today. Two supporting facts found while re-evaluating this plan:

- `plan_for_job()` routes off `detect_apply_channel(job["url"])` — the Notion *Job URL*. There is
  no redirect resolution anywhere in Layer 1, so such a row is classified `linkedin` and never
  offered to Layer 2. Backlog §3 scenario #8 ("resolve the true destination first, then re-route")
  was designed and never implemented; this is the direct cause of the mis-measurement.
- `scripts/sources.py` **discards a real destination on the Indeed path**: `scrape_indeed()` puts
  `externalApplyLink` third in the URL chain behind `job["url"]`, and sets
  `followApplyRedirects: False` so that field mostly holds a wrapper anyway.
  (`scrape_linkedin()` appears to drop `applyUrl` the same way — **measured false**, the field is
  never populated at all; see the findings below. Stated here as originally written because the
  correction is the more useful fact.)

### Measured 2026-07-29 (`scripts/spike_apply_redirect.py`, since deleted)

A throwaway spike measured the resolved apply host directly, including a live Apify probe of both
keyword actors (20 fresh listings each). **The second bullet above turned out to be half wrong,
and the correction matters more than the original claim.**

| Source | Apply-URL field populated | Points somewhere fillable? |
|---|---|---|
| LinkedIn (`valig~linkedin-jobs-scraper`) | **0 / 20** across `applyUrl`, `applyLink`, `companyApplyUrl`, `externalApplyLink`, `link` | n/a — field never exists |
| Indeed, `followApplyRedirects: False` (today) | 3 / 20 `externalApplyLink` | **0** — all indeed.com wrappers |
| Indeed, `followApplyRedirects: True` | 4 / 20 `externalApplyLink` | 4 real, but **0 Greenhouse/Lever/Ashby/Workday** |

1. **LinkedIn is not discarding anything — the field does not exist.** The actor returns no apply
   URL under any of five candidate names, so `job.get("applyUrl")` at `scripts/sources.py:186` is
   dead code, not a dropped signal. And the destination cannot be recovered later either: an
   unauthenticated fetch of a LinkedIn job page returns a ~344 KB guest page carrying
   sign-in/join-now/captcha markers and **zero** `applyUrl` / `externalApplyUrl` / "apply on
   company" occurrences. For a LinkedIn-sourced row the apply destination is **structurally
   unobtainable by this pipeline**, at scrape time or after.
2. **Indeed's discard is real, and `followApplyRedirects` is the whole difference** — off, every
   populated value is an `indeed.com` wrapper; on, all four resolve externally. Cost: 33.0s → 54.1s
   for 20 items (~+64%), against `_apify_run()`'s 400s poll budget, and that helper *raises* rather
   than returning a partial dataset — so flipping the flag without raising the poll count would
   convert a slow scrape into a silently empty one.
3. **But every reachable destination was a custom career site**, not an ATS:
   `careers.cisco.com`, `careers.baptisthealth.net`, `careers.massmutual.com` — Phenom-style,
   classified `unknown`. Only ~20% of Indeed listings expose an external apply link at all; the
   other ~80% are Indeed Apply, permanently manual by rule.

**What that means for this plan.** Finding 3 is the one point where the data *favors* this plan
over [`ashby-workday-custom-fill.md`](ashby-workday-custom-fill.md): custom career sites are
exactly what a live-DOM extension handles and what per-ATS Playwright adapters structurally cannot.
But the addressable volume is ~20% of 90 Indeed rows (≈18 jobs) and **0%** of the 413 LinkedIn
rows. **That is not a trigger.**

**The trigger, restated on measured ground:** this plan is worth building once the tracker actually
holds a meaningful body of `Resume Tailored` rows whose *apply* host is a custom career site or
Workday. Reaching that state is gated on sourcing, not on this plan — see the note below.

**Prerequisite, now sharper than "weight sourcing for volume".** The pipeline's two dominant
sources *structurally cannot* produce a fillable apply URL: LinkedIn yields nothing at all, Indeed
yields ~20% and those are custom sites. Shifting `ENABLED_SOURCES` weight toward
Greenhouse/Lever/Ashby is therefore the **only** mechanism that puts a fillable apply URL in the
tracker, because those sources hand over the ATS URL directly. Do that first; re-measure after.

One addition unchanged by all of the above: if apply volume rises on *Greenhouse* too, that alone
can justify this, since the extension is faster than `--stage 7 --fill` even where Playwright
already works (no headless launch, no drift guard, you see it happen).

**Standing caveat on this plan's own reach:** the extension never fills LinkedIn/Indeed by rule, so
its addressable population is bounded by how many non-aggregator apply hosts the tracker holds —
which is the number the prerequisite above is designed to move.

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
