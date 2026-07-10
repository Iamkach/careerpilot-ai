# Refinement Plans — Overview, Dependencies, and Sequencing

Five plan documents describing proposed changes to the AI job search pipeline. This README indexes
them, records where they **conflict**, and recommends an implementation order.

Baseline: `feat/maverick`. Claims below were re-verified against the code on 2026-07-10; file:line
references are to that state.

## The five plans at a glance

| # | Plan | Lines | Scope | New Notion props | New external cost |
|---|---|---|---|---|---|
| 1 | [`filtering/stage1-filtering-rework.md`](filtering/stage1-filtering-rework.md) | 165 | Fix company denylist false-positives; AI `company_type`; head+tail JD excerpt; surface sponsorship | `Sponsorship` | none |
| 2 | [`reliability/hybrid-agentic-migration-plan.md`](reliability/hybrid-agentic-migration-plan.md) | 239 | AI provider tier split; retries + typed errors; kill the fabricated score of 50; retry queue | `Scoring Attempts`, `Retry` status | ~$3–5/mo metered Haiku |
| 3 | [`sourcing/scraping-sources.md`](sourcing/scraping-sources.md) | 211 | **Research doc.** The two Apify actors are broken/overpriced; surveys alternatives | — | *saves* $29.99/mo |
| 4 | [`sourcing/multi-source-sourcing.md`](sourcing/multi-source-sourcing.md) | 275 | Nine sources behind a registry; real `posted_date`; cross-source fingerprint dedup | `Posted Date`, `Source`, `Applicant Count`, `Salary Range` | $0 (Phase 1) → ~$15/mo (Phase 2) |
| 5 | [`communications/communications-subsystem.md`](communications/communications-subsystem.md) | 488 | Stages 7–8: LinkedIn leads + Hunter-verified cold email; Leads DB; GitHub Actions | new **Leads DB** (~22 props) | Hunter free tier + ~$0.02–9/mo Apify + metered CI |

Plan 3 is the odd one out: it is **analysis, not an implementation spec**. It has no phases and no
file-change table. Its findings, however, invalidate assumptions in plans 4 and 5.

---

## What is actually true today

Read this before any plan. Several plans reason from a baseline that does not hold.

- **Stage 1 is LinkedIn-only.** `INDEED_ACTOR = "bebity~indeed-scraper"`
  (`stage1_scrape.py:38`) returns HTTP 404 — the actor was deprecated by its developer. Because
  `scrape_indeed()` swallows the exception (`stage1_scrape.py:166-170`), every Indeed scrape has
  contributed **zero listings**, leaving only a one-line `✗ Indeed scrape failed` in the log.
- **Three LinkedIn actors are in play, not one.** `bebity~linkedin-jobs-scraper` for search
  (`:36`, a **$29.99/mo rental**, and the payload builder sends `queries`/`timePosted`/`cookie` —
  *not* bebity's documented `title`/`location`/`publishedAt`/`rows`), and
  `curious_coder~linkedin-jobs-scraper` hardcoded inline for enrichment (`:219`). The payload
  fields belong to curious_coder. This reads as a migration that changed the actor constant and
  left the payload untouched. **The LinkedIn numbers are unverified.**
- **Manual "Interested" intake is broken.** `ingest_interested_from_notion()` calls
  `db_find_job_by_url(page["url"])` (`stage1_scrape.py:397`), but that page **lives in the jobs DB
  and holds that URL**, so `_query_db` (`utils.py:449-458`) matches the page against *itself*.
  Every Interested row with a URL takes the `⊘ Already in DB, retiring` branch and is promoted
  straight to `Scraped` **with no score and no cached JD**. `CLAUDE.md` documents this path as
  working. It has not been.
- **AI failures fabricate data.** `score_jobs_batch()` catches every exception and returns
  `score=50, sponsorship="unknown"` for the whole batch (`stage1_scrape.py:380-381`). Since the
  gate only drops `sponsorship == "no"`, a failed batch writes invented scores to Notion with no
  warning. Same defect for jobs the model omits (`:375`, `:427`, `:575`). No retry logic exists
  anywhere in the codebase.
- **The denylist silently drops real product companies.** `is_skipped_company()`
  (`stage1_scrape.py:265-279`) documents "exact-name match" but performs a substring test. Short
  entries eat legitimate names: `UST` → c**ust**omer.io, `Dice` → in**dice**s, `iGate` →
  nav**igate**, `Numero` → **numero**us. `Qualcomm` (`settings.py:43`) is simply a wrong entry.
  These drops happen before the AI runs and surface only in the drop log.
- **`_notion_write_job()` (`utils.py:300-320`) has three latent bugs**, each independently
  rediscovered by four of the five plans: it hardcodes `Status="Scraped"`; `if job.get("ats_score"):`
  discards a genuine score of `0`; and a bare `except: return None` turns any schema mismatch into
  an undiagnosable zero-row run.
- **Collected-then-discarded:** `applicant_count` and `salary_range` are parsed in stage 1 and
  never reach Notion. `TARGET_COMPANIES` (`settings.py:15`) is referenced nowhere.
- **`APIFY_API_TOKEN` is a live plaintext literal** at `settings.py:142` and is in git history.

---

## Conflicts between the plans

These are **not** flagged in the plans themselves. Ignoring them means writing the same code twice.

### C1 — Plans 1 and 2 both rewrite `score_jobs_batch()`, incompatibly

Both replace the same `except → score 50` block, and both change the function's return shape. They
disagree on what happens next:

| | Plan 1 | Plan 2 |
|---|---|---|
| On AI failure | fail open, write the job | fail open, write the job |
| Status written | `Needs Review` | `Retry` |
| Score | `None` + `scored: False` flag | `None` |
| Recovery | none — human reviews by hand | `rescore_retry_jobs()` re-scores from the cached JD, capped by `Scoring Attempts` |

Plan 2's failure model is strictly better: it recovers automatically, costs no Apify call (the JD
is already cached in the page body), and bounds itself with an attempt cap. Plan 1's contribution
is the *filter* logic, not the failure model. **Merge them; take Plan 2's failure model and Plan
1's filters.** Landing them separately means one rewrites the other's 60 lines.

### C2 — Plans 1 and 2 add retry at different layers

Plan 1 adds a separate `ai_chat_retry()` wrapper that raises. Plan 2 puts retry **inside**
`ai_chat()` with typed exceptions (`AIChatError`, `AIUsageCapError`) plus a usage-cap failover to
the metered API. Plan 2's shape covers all four `_BACKENDS` and every existing caller for free.
Plan 1 even notes its helper is the one "plan-doc §1 wants for `stage3_outreach.py`" — it is aware
of the overlap and proposes the weaker shape anyway. **Take Plan 2's.**

### C3 — Three names for one concept, and none reuse the existing status

Plan 1 introduces `Needs Review`. Plan 2 introduces `Retry`. Neither string appears anywhere in the
codebase. The documented schema already carries **`Human Review`** as a manual-only off-pipeline
option. Three names for "the AI did not score this" is exactly the drift `CLAUDE.md` warns about.
Pick one before either lands.

### C4 — Plan 5's dependency on Plan 1 is not satisfied by Plan 1

Plan 5 (§"§2 dependency") requires Plan 1 to extract a standalone
`classify_company_type(companies) -> dict` out of `score_jobs_batch()`. Plan 1 (§4) **explicitly
declines**: "Keep it a **single combined call** — a separate classify-first pass would add a second
round-trip." As written, Plan 1 leaves `company_type` welded to a prompt that needs a résumé and a
JD and cannot accept a bare company name. Plan 5 must either fund the extraction itself or fall
back to `is_skipped_company()` alone (which it lists as the interim path).

### C5 — Plan 4 is built on the dead actor Plan 3 identified

Plan 4's `ENABLED_SOURCES` defaults to `["linkedin", "indeed", ...]`, and its §1c says to "fix the
Indeed date bug by sending the actor's max-age param." **You cannot fix a date parameter on an
actor that returns 404.** Plan 4 also keeps six Apify keyword sources and never engages Plan 3's
central recommendation (JobSpy, free and self-hosted, covering LinkedIn + Indeed + Glassdoor +
Google Jobs in one call). Plan 3 and Plan 4 need reconciling before either is built. This is the
sharpest inconsistency in the set.

### C6 — Plan 3 makes Plan 5 substantially cheaper

Plan 5 notes it directly: `valig~linkedin-jobs-scraper` returns `recruiterName` + `recruiterUrl`
with no cookie, so **if the actor swap lands first, prong 1's job-linked contact data arrives free
as a side effect of scraping**, and the `coregent` lead actor (~$2.40/1k) is not needed for Mode A
at all. Sequencing 3 before 5 removes a vendor.

### C7 — `_notion_write_job()` is modified by four plans

Plans 1, 2, 4, and 5 each add different properties to it, and each independently proposes to fix
the same bare-`except`. Only Plan 5 generalizes the writer (`db_id` param on `_query_db`,
`_notion_create_page`, `_safe_select`, propagate exceptions). Whoever touches it first should land
the **error-surfacing fix** once, for everyone — a schema mismatch currently manifests as a total
scrape outage with no diagnosable cause, and every plan that adds a Notion property walks into it.

### C8 — One bug blocks two plans

The dedup self-match (Plan 2 §3.5) blocks Plan 2's own retry queue *and* Plan 4's fingerprint set —
a queued row would be dropped as a duplicate of itself on the next scrape. Plan 2 flags this;
Plan 4 inherits the trap through `db_get_all_jobs()` without noticing.

---

## Recommended order

The instinct is to start with the plan that addresses the loudest pain (filtering). Don't. Two
cheap items must land first, because everything else is measured against a baseline that is
currently unknown and a data path that is currently broken.

### Step 0 — Rotate `APIFY_API_TOKEN` *(not a feature; do it now)*

`config/settings.py:142` is a live token in git history. Rotate it, move it to `os.environ.get`.
This is the only item that is a security incident rather than a feature, and it **must** precede
Plan 5, which moves secrets into GitHub Actions.

### Step 1 — Plan 3's actionable core: verify and fix the scrapers *(smallest diff in the set)*

Run each actor once with `maxItems=3` and dump the raw dataset keys. Confirm whether the LinkedIn
payload matches its actor. Then swap Indeed → `misceres~indeed-scraper` and decide LinkedIn
(`valig`, at ~1/100th the rental's cost, no cookie, and it carries the recruiter fields Plan 5
wants). Two constants and two payload builders.

*Why first:* Stage 1 has been LinkedIn-only, so nobody knows the real listing volume. Plans 1, 2,
and 4 all tune filters, dedup, and scoring against that volume. Plan 4 says so itself: *"Read the
drop logs — the real baseline for what Stage 1 ingests is unknown."* This step is a few hours and
de-risks four plans.

### Step 2 — The dedup self-match fix (Plan 2 §3.5) *(~10 lines)*

Give `db_find_job_by_url()` an `exclude_page_id` parameter. Fixes manual intake **today**, and
unblocks Plan 2's retry queue and Plan 4's fingerprint dedup (C8). While here, fix
`scrape_job_urls()`'s silent `{}` return — a failed enrichment and an empty one must not look alike.

### Step 3 — Plan 1's *pure-function half* — the true "implement first" feature

Plan 1 splits cleanly along the collision line from C1:

- **1a — no collisions, ship immediately:** word-boundary company matching (`_tokens`,
  `_strip_suffix`, `_subseq`), drop `Qualcomm`, `_jd_excerpt(head=1200, tail=800)` so the model can
  finally see the EEO/work-authorization block that lives at the *bottom* of a JD. Pure functions,
  unit-testable offline, no Notion schema change, no AI call. This is the highest value-per-line
  change in the entire directory and it directly answers the user's two stated complaints.
- **1b — collides with Plan 2:** everything touching `score_jobs_batch()` (the `company_type`
  field, the `scored` flag, the status branch). **Hold until Step 4.**

### Step 4 — Merge Plan 2 + Plan 1b into one work item

Resolve C1/C2/C3 first: adopt Plan 2's `Retry` failure model and in-`ai_chat` retry with typed
errors; adopt Plan 1's `company_type` classification and `Sponsorship` property; settle on **one**
status name. Land Plan 5's error-surfacing fix to `_notion_write_job` here (C7), since this step
already adds Notion properties.

Decide C4 now too: if `classify_company_type()` is extracted as a standalone, Plan 5 gets cheaper
later; if not, record that Plan 5 uses `is_skipped_company()` alone.

### Step 5 — Plan 4, Phase 1 only

The three ATS boards (Greenhouse, Lever, Ashby) are free, unauthenticated, expose true posted dates,
and return the full JD — which also gives Stage 2 cleaner input than a LinkedIn description blob.
They structurally exclude staffing firms, because those firms do not post client roles on their own
Greenhouse board. `TARGET_COMPANIES` finally gets a consumer.

**Hold Phase 2.** Four more Apify sources cost ~$15/mo, and Glassdoor + Wellfound require adopting
an anti-detect-browser ToS posture through a third party.

Reconcile C5 before starting: either drop `indeed` from `ENABLED_SOURCES` or adopt Plan 3's JobSpy
recommendation.

### Step 6 — Plan 5

Only after its **Phase 0 spike** returns. Four live unknowns gate the design — whether Hunter's
Email Finder returns a terminal `verification.status` inline (this alone decides whether capacity is
~50 or ~33 people/month), whether the free tier honors `linkedin_handle` (which would skip domain
resolution entirely), the billing edges, and the coregent field map. Coding before the spike means
guessing at exactly the things the plan's governing rule forbids guessing about.

---

## Complexity ranking

Ranked by blast radius, new surface area, external dependencies, and unresolved unknowns.

| Rank | Plan | Why |
|---|---|---|
| **1 — most complex** | **5 · Communications** | Two new stages, a **new Notion database** (~22 properties), new `scripts/credits.py`, a digest refactor, **two new vendors** (Hunter.io, coregent), and **a new execution model** — GitHub Actions, which forces a provider split (`claude_code` cannot run headless), kills the SQLite ledger (ephemeral runners), and strands `output/` (drafts must go into the Notion page body). Adds headless Gmail OAuth, GDPR/personal-data obligations, a credit budget, and a human approval gate. A **blocking Phase-0 spike** with four unknowns precedes any code. Depends on Plan 1 (for a function Plan 1 declines to write — C4) and benefits from Plan 3 (C6). It is the only plan that changes *how and where the pipeline runs*. |
| 2 | **4 · Multi-source sourcing** | New `scripts/sources.py`, two registries, and a **restructure of `run()`** from per-role incremental scoring to global gather → collapse → filter → score (necessary because a duplicate can span both roles *and* sources). ATS token discovery carries an unequal, unverifiable slug-collision risk — Greenhouse returns `company_name` and can be checked; Lever and Ashby cannot. Four Notion properties. Phase 2 adds real spend and ToS exposure. Built on a dead actor (C5). |
| 3 | **2 · Reliability / hybrid provider** | Touches `settings.py`, `utils.py`, `stage1_scrape.py`, `workflow.py`, `run.py`. Provider tier routing + typed exceptions + usage-cap failover + a retry queue with an attempt cap + two Notion schema changes. Genuinely intricate, but contained to code that already exists. Contains the one **blocking bug fix** in the set (§3.5) and reintroduces metered cost (~$3–5/mo). |
| 4 | **1 · Stage-1 filtering** | Confined to `stage1_scrape.py`, `utils.py`, `settings.py`. One Notion property. Its core is pure functions with offline unit tests. Its only real hazard is the `score_jobs_batch()` collision with Plan 2 (C1). |
| **5 — least complex** | **3 · Scraping sources** | Not an implementation plan. Its actionable core is two actor constants and two payload builders — the smallest diff in the directory, and the one that de-risks the most other work. |

**Most complex: Plan 5.** **Implement first: Plan 3's actor verification (Step 1), then the dedup
fix (Step 2), then Plan 1a (Step 3)** — the first feature that changes what the user sees.

---

## Cost summary

| Change | Δ monthly |
|---|---|
| Drop the `bebity` LinkedIn rental (Plan 3) | **−$29.99** |
| `valig` LinkedIn + `misceres` Indeed, at current volume | ~+$0.50 |
| Plan 2 fast tier → metered Haiku | +$3–5 |
| Plan 4 Phase 1 (ATS boards) | $0 |
| Plan 4 Phase 2 (four Apify sources, daily) | +$15 |
| Plan 5 (Hunter free tier; Apify Mode A) | ~+$0.02, or +$9 with Mode B |

Steps 0–4 land **net cheaper than today**.

---

## Open questions

Answers change the plans; none block Steps 0–2.

1. **Status naming (C3).** `Retry`, `Needs Review`, or reuse the existing `Human Review` for jobs
   the AI failed to score? One name, please.
2. **LinkedIn actor (Step 1).** `valig` (cheapest, carries recruiter fields → free lead data for
   Plan 5) or `curious_coder` (matches the payload already in the code, so a zero-payload-change
   swap)?
3. **JobSpy vs. Apify (C5).** Plan 3 recommends replacing both actors with the free self-hosted
   JobSpy; Plan 4 assumes Apify throughout. JobSpy is free and covers more boards, but it
   rate-limits on LinkedIn without proxies and its release cadence is slow. Which way?
4. **Indeed at all?** It has contributed zero listings for the life of the project. Is it worth
   fixing, or should it be dropped from `ENABLED_SOURCES`?
5. **`classify_company_type()` extraction (C4).** Fund the standalone extraction in Step 4 so Plan 5
   can reuse it, or let Plan 5 rely on `is_skipped_company()` alone?
6. **Plan 4 Phase 2.** Glassdoor and Wellfound prohibit scraping, and the actors advertise
   anti-detect browsers to bypass DataDome/Cloudflare. Is that posture acceptable, or should Phase 2
   stop at the three free ATS boards?
7. **GitHub Actions (Plan 5).** Adopting CI means scheduled runs bill metered tokens and can no
   longer use the Claude Code subscription. Accept, or keep everything local and manual?
8. **`Sponsorship` semantics.** Plan 1 keeps `unknown` jobs and surfaces them. Confirm that's still
   wanted — the regex only catches postings that *explicitly* deny sponsorship, so `unknown` will be
   the large majority.
