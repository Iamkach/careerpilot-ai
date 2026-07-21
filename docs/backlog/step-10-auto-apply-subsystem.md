# Step 10 — Auto-Apply subsystem (Stage 7)

**Status:** **Phases 1–2 landed** (2026-07-19, branch `feature/step-10-auto-apply`). Phase 3
(deliberate submit) deferred pending real-world use of the fill path. Phase 4 (agentic long tail)
not started. Sections 1–8 below are the original analysis, kept as the design rationale; §11
records what actually shipped and what external research changed.
**Priority:** P2 — high user value, but the highest *execution risk* in the roadmap (anti-bot,
ToS, per-site fragility). Ship the safe slice first.
**Depends on:** Stage 2 (tailored `.docx` per job), Notion status pipeline, `scripts/sources.py`
(the `source` / URL-domain routing key this reuses).
**Size:** L–XL, but *phaseable* — a genuinely useful semi-auto slice is S–M.

## 1. What "auto-apply" means here

Today the pipeline stops one step short of applying. After `--evaluate`, a job sits at
`Resume Tailored` with a tailored `.docx` and a digest line; **the human opens the job URL and
fills the application by hand.** No stage sets `Applied` — it is a manual Notion edit.

The request: once a job is `Reviewed`, drive the application submission itself. The core question
this doc answers is *how far that can actually go per source*, and where a human must stay in the
loop.

**The single most important finding up front:** there is **no candidate-usable application-submit
API** for the mainstream ATSes. Greenhouse's documented submit endpoint
(`POST /v1/boards/{token}/jobs/{id}`) requires the *employer's* board API key over Basic Auth
([Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)); Lever and Ashby's
submit APIs are likewise employer-authenticated. Only the **read** side (job list, JD, and the
`?questions=true` application-field schema) is public. Therefore **auto-apply is fundamentally a
browser-automation problem, not an API problem** — every real submit path is a rendered web form.
That reframes the entire design: the value is not "call an apply API," it's "reliably fill and
submit heterogeneous web forms, and know when to stop."

## 2. The two automation levels (both analyzed, per the request)

| | **Semi-auto (assisted)** | **Fully hands-off** |
|---|---|---|
| Behavior | Auto-fill every resolvable field, upload the tailored resume, then **pause for one human confirm before the final Submit click** | Attempt end-to-end submit with zero human input wherever technically possible |
| Captcha/auth | Hands off to human cleanly (this is the *designed* exit, not a failure) | Must solve or route around — captcha-solving services, residential proxies, stored sessions |
| Error blast radius | Low — human catches a mis-mapped field or wrong-JD before submit | High — a wrong answer to "are you authorized to work without sponsorship?" is submitted silently and is unretractable |
| ToS / ban risk | Low on ATS-hosted forms (candidate is present, one submit); still **do not** touch LinkedIn/Indeed Easy Apply | High — bulk automated submission is exactly what LinkedIn §8.2 and Indeed prohibit and actively flag ([LinkedIn automation ToS 2026](https://northlight.ai/blog/is-linkedin-automation-against-the-rules)) |
| Reputational cost | You never send a bad application under your name | A hallucinated cover-letter answer or duplicate app reaches a real recruiter under your name |
| Effort to ship | S–M for the first source class | XL, per-site, ongoing maintenance treadmill |

**Recommendation:** default to **semi-auto everywhere**, and let the *source class* decide how
much of the form is pre-filled before the human confirm (Section 4). Reserve any fully-hands-off
submit for a single, opt-in, low-risk class (Greenhouse-hosted forms with **zero** custom
knockout questions and no captcha), behind an explicit `--submit --yes-i-mean-it` flag and a hard
daily cap. Never fully automate LinkedIn/Indeed. This matches the repo's existing governing
posture — Stage 3 drafts outreach but does **not** auto-send; a human reviews `output/outreach/`
first. Auto-apply should inherit that "prepare fully, submit deliberately" stance.

## 3. All the scenarios (what actually happens when you try to apply)

Enumerated so the router (Section 5) has a case for each:

1. **Public read, form submit, no login, no captcha** — Greenhouse/Lever/Ashby *hosted* forms for
   many small/mid companies. The happy path. Fill + upload + submit is mechanically possible in a
   browser. → best automation candidate.
2. **Form + invisible/anti-bot captcha** — reCAPTCHA v3, hCaptcha, Cloudflare Turnstile fire on
   submit. Common on Ashby and higher-traffic Greenhouse boards. → semi-auto hands off at the
   captcha.
3. **Account required before applying** — Workday, iCIMS, Taleo, SuccessFactors, Oracle. Each
   company is a *separate* tenant needing its own account + email verification loop. This is the
   single largest slice of "Apply on company site." → account-provisioning + verification problem;
   assisted only.
4. **Multi-page dynamic form** — Workday especially: 4–8 steps, resume "parse then correct every
   field it got wrong," education/experience repeaters, voluntary disclosures. Fragile to
   automate; field IDs are dynamic. → assisted, agentic driver.
5. **Authenticated-platform quick-apply** — LinkedIn Easy Apply, Indeed Apply. Technically a few
   clicks, but requires a logged-in session and is **explicitly ToS-prohibited and behaviorally
   flagged** ([LinkedIn](https://northlight.ai/blog/is-linkedin-automation-against-the-rules)). →
   **route to manual**, provide a pre-filled answer sheet, never drive the submit.
6. **Knockout / screening questions** — free-text ("why this company?"), dropdowns ("years of
   React"), work-authorization and sponsorship gates, salary expectation, notice period,
   demographic/EEO (voluntary). Some are disqualifying if wrong. → deterministic answers from a
   profile where possible; LLM-drafted free-text behind human review; **never guess** work-auth or
   sponsorship.
7. **File-upload variants** — resume required, cover letter optional/required, portfolio, writing
   sample. Format constraints (PDF-only vs docx). → resume is Stage 2's `.docx`; may need on-the-fly
   PDF conversion.
8. **External redirect** — LinkedIn/Indeed listing whose "Apply" bounces to a company ATS (case 1–4
   again). → resolve the true destination first, then re-route.
9. **Already applied / duplicate** — re-running the stage, or the same req cross-posted. → hard
   idempotency gate on Notion status + `job_fingerprint` (already exists in `sources.py`).
10. **Login/session expiry mid-run, IP/rate blocks, bot-fingerprint challenges** — for any
    stored-session path. → typed errors + back off, never hammer.
11. **Form changed / selector drift** — ATS updates its markup; a hard-coded selector map breaks
    silently. → prefer schema-driven (Greenhouse `questions`) or agentic (self-locating) filling
    over brittle CSS selectors; verify a known field resolved before trusting the fill.

## 4. Source-class feasibility matrix

Routing key = the job's `Source` field / URL domain (same key `sources.py` already uses).

| Source class | Read schema? | Submit path | Captcha likelihood | Auth needed | Recommended automation |
|---|---|---|---|---|---|
| **Greenhouse (hosted form)** | ✅ `?questions=true` gives exact field schema | Browser fill of `boards.greenhouse.io/{token}/jobs/{id}` (API submit needs employer key) | Low–med | None | **Semi-auto, first target.** Optional hands-off only if 0 custom questions + no captcha |
| **Lever (hosted form)** | Partial (postings JSON, no question schema) | Browser fill of `jobs.lever.co/{token}/{id}/apply` | Low–med | None | Semi-auto, second target |
| **Ashby (hosted form)** | Partial | Browser fill of `jobs.ashbyhq.com/{token}/{id}` | **Med–high** (Turnstile common) | None | Semi-auto, expect captcha handoff |
| **Workday / iCIMS / Taleo / SF / Oracle** | ❌ | Multi-page form, per-company account | Med | **Account + email verify** | Assisted/agentic only; account provisioning is the real cost |
| **LinkedIn Easy Apply** | n/a | Authenticated quick-apply | Behavioral flagging | **Logged-in session** | **Manual only** — pre-filled answer sheet, no automated submit (ToS §8.2) |
| **Indeed Apply** | n/a | Authenticated quick-apply | Med | Session | **Manual only** — same posture |
| **Company careers page (custom)** | ❌ | Arbitrary form | Unknown | Varies | Agentic driver, always human-confirm |

## 5. Proposed architecture — a capability router (not a single scraper)

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
  map result → Notion status  (see Section 6)
```

Three execution *substrates* are available and should be used by tier, not one-size-fits-all:

- **Schema-driven browser fill** (Playwright + Greenhouse `questions` schema) — deterministic,
  fast, cheapest to run; best where the field schema is knowable (Greenhouse). Brittle to markup
  changes, so gate on "did the expected fields resolve?"
- **Agentic browser driver** (Claude-in-Chrome / computer-use) — self-locates fields, handles
  novel/multi-page forms (Workday), reads the page to decide. Slower, costs model calls, but
  survives selector drift and is the only realistic path for the long tail. Pauses for the human
  on captcha/auth by design.
- **No-automation handoff** (manual_adapter) — for ToS-prohibited or unknown targets: produce a
  filled-in **answer sheet** (every question + the answer we'd give + the resume path + a deep
  link) so the human applies in <60s without re-deriving anything.

**Governing rule (borrowed from Step 7's spec):** *the profile supplies facts; AI only drafts
prose.* The model never invents an answer to a work-authorization, sponsorship, salary, or
yes/no eligibility question — those come from a structured `APPLICATION_PROFILE` or the field is
flagged `review_required`. A code-level validator enforces this, not the prompt.

## 6. Notion status & schema changes

New status transitions (extend the existing `Status` select; add options by hand — the Notion API
won't create select options, same footnote as `Retry` in CLAUDE.md):

```
Reviewed → Resume Tailored → [Application Queued] → [Applying] → Applied
                                        │
                                        ├──→ [Needs Human: Captcha]
                                        ├──→ [Needs Human: Auth/Account]
                                        ├──→ [Needs Human: Question]   (unanswerable knockout/free-text)
                                        └──→ [Apply Failed]            (typed error, safe to retry)
```

New properties (all written the optionally-present way `_notion_write_job()` already uses, so
their absence never breaks a write):

- `Apply Channel` (select) — greenhouse/lever/ashby/workday/linkedin/manual, for triage.
- `Apply Attempts` (number) — bounded retry, mirrors `Scoring Attempts`.
- `Application Log` (rich_text or page-body block) — audit trail of what was filled/submitted.
- `Needs Human Reason` (rich_text) — populated on any `Needs Human:*` exit.

Reuse existing plumbing: idempotency via status + `job_fingerprint()`; "prepare, don't auto-send"
gate via a `--submit` flag exactly like Stage 4's `--send`.

## 7. Hurdles & mitigations (the blockers, explicitly)

- **Captcha (reCAPTCHA/hCaptcha/Turnstile)** — *do not* build captcha-solving into the default
  path. Semi-auto treats a captcha as the designed human-handoff point. A paid solver
  (2Captcha/anti-captcha) is a fully-hands-off-only, opt-in, per-user-keyed extra — flagged as
  higher ToS risk.
- **Authentication** — LinkedIn/Indeed session cookies (`LINKEDIN_SESSION_COOKIE` already exists,
  empty) are brittle and expire; and using them to *apply* is the ToS violation. Workday-style
  per-company accounts need a credential vault + email-verification reader (Gmail MCP is already
  connected and could read verification links) — treat account provisioning as its own phase.
- **Knockout questions** — the disqualification risk. Work-auth/sponsorship/salary answers come
  from `APPLICATION_PROFILE` only; anything unmapped → `Needs Human: Question`, never a guess.
- **EEO/demographic** — default to "Decline to self-identify" unless the user set an explicit
  preference. Never LLM-guess protected attributes.
- **Selector drift & silent form changes** — prefer schema-driven (Greenhouse) or agentic
  (self-locating) filling; assert an expected field resolved before submit; on mismatch → fail
  safe to `Apply Failed`, never submit a half-filled form.
- **Duplicate/double submit** — status gate + fingerprint; write `Applying` *before* the attempt
  so a crash can't silently double-apply.
- **Legal/ToS** — LinkedIn §8.2 and Indeed prohibit automated applying and flag it behaviorally
  ([source](https://northlight.ai/blog/is-linkedin-automation-against-the-rules)). Hard rule:
  **no automated submit on LinkedIn/Indeed**, ever, at any automation level.
- **Rate/IP/fingerprint blocks** — cap applications/day; human-paced timing; typed errors +
  backoff like `AIChatError`; never blind-retry a bot-challenge.
- **Wrong resume / wrong company** — pre-submit verification: confirm the tailored `.docx`
  actually matches this `page_id` and the form's company matches the job's company (cheap string
  check) before any submit.

## 8. Phased plan (ship the safe slice first)

**Phase 0 — spike (blocking, do first).** Against 2–3 *real* Greenhouse-hosted jobs already in the
tracker: (a) confirm `?questions=true` returns a field schema we can map end-to-end; (b) manually
walk the hosted form and record whether a captcha fires on submit and what the exact field
`name`s are; (c) decide the browser substrate (Playwright vs Claude-in-Chrome) from what the real
forms look like. Nothing downstream is coded until this returns — same discipline as Step 7's
Phase 0.

**Phase 1 — read + plan, zero submit (this PoC).** `scripts/autoapply.py`: detect channel, fetch
the Greenhouse `questions` schema, build the application plan from `APPLICATION_PROFILE` + tailored
resume, emit a readiness report (fully-answerable vs needs-human), write `Application Queued` /
`Needs Human: Question` to Notion. No browser, no submit. Immediately useful (turns every review
into a <60s manual apply) and de-risks the schema mapping.

**Phase 2 — semi-auto browser fill for Greenhouse.** Playwright fills the hosted form from the
Phase-1 plan, uploads the resume, **stops before submit**, screenshots for the human. Add Lever.

**Phase 3 — deliberate submit + Ashby.** `--submit` behind a daily cap; handle Ashby's captcha as
a clean handoff.

**Phase 4 — agentic long tail (Workday/custom).** Claude-in-Chrome driver, account-aware, always
human-confirm. Highest maintenance; last for a reason.

**Never:** automated submit on LinkedIn/Indeed. `manual_adapter` answer sheet only.

## 9. This PoC — `scripts/autoapply.py`

Implements **Phase 1** for the **Greenhouse** class (the easiest, most standardized source, and
the only one exposing a public field schema). It is **dry-run by default** and never submits:

- `detect_apply_channel(url)` — domain → channel, so the router shape exists from day one.
- `fetch_greenhouse_questions(token, job_id)` — real, unauthenticated GET of the actual
  application-field schema.
- `build_application_plan(questions, profile, resume_path)` — maps each field to a value from a
  sample `APPLICATION_PROFILE`; free-text/unmapped fields are flagged `review_required` (never
  guessed).
- `readiness_report(plan)` — fully-answerable vs needs-human breakdown.
- Notion write is **stubbed/guarded** (prints intended `Application Queued` / `Needs Human`
  transition) so the PoC runs without touching the live tracker.

Because the sandbox has no egress to `boards-api.greenhouse.io`, the PoC ships with a
`--sample` mode that runs the full mapping against a bundled real-shaped Greenhouse `questions`
payload, and a `--url` mode for live validation once run in an environment with network. Live
validation against 2–3 real jobs is the Phase-0 spike above — deliberately **not** yet run,
tracked here like the repo's other "manual QA never run" items in `docs/TODO.md`.

## 10. Open questions for the human — ANSWERED (2026-07-19)

1. **Automation ceiling** → keep everything semi-auto for now. Phase 2 fills, the human submits.
   Revisit hands-off submit (Phase 3) only after the fill path has been used in anger.
2. **Account provisioning (Phase 4)** → still open; Workday remains manual and deferred.
3. **EEO default** → preset bank, `EEO_RESPONSES` in `config/settings.py`, defaulting to decline
   but user-editable per field. Extended to `COMMON_QUESTION_PRESETS` for recurring screeners.
4. **Daily cap** → `AUTOAPPLY_DAILY_CAP = 10`.

Eligibility facts were also settled: `work_authorized = True`, `requires_sponsorship = True`.

## 11. What shipped, and what the research changed

### Landed (Phases 1–2)

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

**Ergonomics that landed after the core (developer-flag ask):** `--setup-profile` captures the
application answers once into a git-ignored JSON overlay instead of editing `config/settings.py`
per change; `--dry-run` (+ `--limit N`) samples the stage on real jobs — real answer sheets, zero
Notion writes, no browser — so the output can be eyeballed before committing to the live path.

### Findings from surveying existing implementations

Researched before implementing, since this is well-trodden ground. Six findings changed the design:

1. **The flagship project is dead.** AIHawk / `Auto_Jobs_Applier_AI_Agent` — the most prominent
   open-source auto-applier — was **archived read-only on 2026-05-17**. Its selector-drift bug
   reports ("almost every second class differs"; `job-card-list__footer-wrapper` → `…-wrapper-v2`)
   were closed *not planned*. Selector drift is what kills these projects.
   → Layer 1 / Layer 2 are decoupled so drift costs a feature, not the subsystem; Layer 2 prefers
   label-text selectors over CSS classes, and aborts on `drift` rather than half-filling.
2. **Bots lie about success.** AIHawk "claims to apply for jobs on pages where it hasn't actually
   applied." → `WRITABLE_STATUSES` excludes `Applied`; the stage is structurally incapable of
   claiming an application it didn't make, asserted in `test_autoapply_notion.py`.
3. **Recruiter-side bot detection is real.** ATSes flag mass-submitted applications as low-intent
   before a human reads them; mass-apply converts at 0.1–2%. → the daily cap is a quality guard.
4. **LinkedIn thresholds quantified** (<15/day safe, 30+ red; ~23% of automation users restricted
   within 90 days), and one AIHawk bug had the bot clicking recruiter *message* buttons
   mid-conversation. → `FILLABLE_CHANNELS` excludes LinkedIn/Indeed by rule.
5. **Turnstile stalls silently** rather than erroring. → every wait is bounded; a timeout is
   classified as a probable challenge and handed off, never retried.
6. **Greenhouse does not server-side validate required fields**, and `?questions=true` is confirmed
   still live. → the plan-level required-field gate is the only guard, so it is strict.

Also confirmed: **no candidate-usable submit API exists** — Greenhouse's docs explicitly warn a
direct POST "would reveal your secret key to anybody that views source", since the endpoint
authenticates as the employer. The browser-automation premise of this whole spec holds.

Sources: [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html) ·
[applications endpoint](https://github.com/grnhse/greenhouse-api-docs/blob/master/source/includes/job-board/_applications.md) ·
[AIHawk issues](https://github.com/AIHawk-FOSS/Auto_Jobs_Applier_AI_Agent/issues) ·
[LinkedIn automation ToS](https://northlight.ai/blog/is-linkedin-automation-against-the-rules) ·
[auto-apply detection](https://www.crossclassify.com/resources/articles/recruitment/how-to-detect-auto-apply-candidate-fraud-before-it-pollutes-your-ats/) ·
[Turnstile under Playwright](https://www.capsolver.com/blog/cloudflare/playwright-blocked-by-cloudflare-turnstile-causes-fix)

### Known gaps shipped knowingly

- **No docx→PDF.** Stage 2 emits `.docx` only; a converter needs LibreOffice/Word. A PDF-only
  upload stops as `pdf_only` rather than uploading a file the form rejects.
- **Live schema fetch validated once; fill path not, and mapping gaps found.** The Greenhouse
  `?questions=true` fetch was run against a real tracker job (SmithRx) and worked — 25 fields
  mapped — confirming the Phase-1 read premise on a live board. It exposed two mapping bugs still
  open: the structured-address block (`Legal First/Last Name`, `Address Line 1/2`, `City`,
  `State`, `Country`, `Zip Code`, `Address Type`) is unmapped, and Greenhouse's two-rows-per-
  attachment question double-counts Resume/Cover Letter. The **Layer-2 fill path has still never
  run against a live form.** See `docs/TODO.md` for the full write-up and next steps.
- **Six `Status` select options must be hand-added in Notion** before stage 7 can transition
  anything — `db_update_status_verified()` fails loudly rather than silently no-opping.
