# Refinement Plans — Consolidated Analysis, Conflicts, and Execution Order

Five plan documents describe proposed changes to the AI job-search pipeline. This README indexes
them, records where they **overlap and conflict**, answers the two scope questions (does one plan
push another out of scope? does one force another to change implementation?), and recommends a
priority order that separates sequential steps from independent ones.

Baseline: `feat/maverick`. **Every code-level claim below was re-verified against the source on
2026-07-10**; `file:line` references are to that state. Where an earlier draft of this README was
wrong, the correction is called out explicitly.

## The five plans at a glance

| # | Plan | Lines | Scope | New Notion props | New external cost |
|---|---|---|---|---|---|
| 1 | [`filtering/stage1-filtering-rework.md`](filtering/stage1-filtering-rework.md) | 165 | Fix company denylist false-positives; AI `company_type`; head+tail JD excerpt; surface sponsorship | `Sponsorship` | none |
| 2 | [`reliability/hybrid-agentic-migration-plan.md`](reliability/hybrid-agentic-migration-plan.md) | 239 | AI provider tier split; retries + typed errors; kill the fabricated score of 50; retry queue | `Scoring Attempts`, `Retry` status | ~$3–5/mo metered Haiku |
| 3 | [`sourcing/scraping-sources.md`](sourcing/scraping-sources.md) | 211 | **Research doc.** The two Apify actors are broken/overpriced; surveys alternatives | — | *saves* $29.99/mo |
| 4 | [`sourcing/multi-source-sourcing.md`](sourcing/multi-source-sourcing.md) | 275 | Nine sources behind a registry; real `posted_date`; cross-source fingerprint dedup | `Posted Date`, `Source`, `Applicant Count`, `Salary Range` | $0 (Phase 1) → ~$15/mo (Phase 2) |
| 5 | [`communications/communications-subsystem.md`](communications/communications-subsystem.md) | 488 | Stages 7–8: LinkedIn leads + Hunter-verified cold email; Leads DB; GitHub Actions | new **Leads DB** (~22 props) | Hunter free tier + ~$0.02–9/mo Apify + metered CI |

Plan 3 is the odd one out: it is **analysis, not an implementation spec** — no phases, no
file-change table. Its findings invalidate assumptions in Plans 4 and 5.

---

## Verification summary — what is actually true today

Read this before any plan. Several plans reason from a baseline that does not hold. Every row was
checked against the current source.

| Claim | Evidence |
|---|---|
| **Stage 1 is LinkedIn-only.** `INDEED_ACTOR = "bebity~indeed-scraper"` returns HTTP 404 (actor deprecated); `scrape_indeed()` swallows the exception, so every Indeed scrape has contributed **zero** listings | `stage1_scrape.py:38`, `:168-170` |
| **The LinkedIn payload mismatches its actor.** The constant is `bebity~linkedin-jobs-scraper` but `_linkedin_payload_base()` sends `queries`/`timePosted`/`cookie` — those are **curious_coder**'s fields. Reads as a migration that changed the constant and left the payload. **LinkedIn numbers are unverified.** | `stage1_scrape.py:36` vs `:79-90`; enrichment hardcodes `curious_coder` at `:219` |
| **Manual "Interested" intake is broken.** `ingest_interested_from_notion()` calls `db_find_job_by_url(page["url"])`, but that page lives in the jobs DB **and holds that URL**, so the query matches the page against *itself*. Every Interested row with a URL is retired straight to `Scraped` with no score and no cached JD. `CLAUDE.md` documents this path as working; it has not been. | `stage1_scrape.py:397` → `_query_db` `utils.py:454` |
| **AI failures fabricate data.** `score_jobs_batch()` catches every exception and returns `score=50, sponsorship="unknown"` for the whole batch. The gate only drops `sponsorship=="no"`, so a failed batch writes invented scores with no warning. Same defect for omitted jobs and the `run()`/ingest misses. No retry logic exists anywhere. | `stage1_scrape.py:381`; misses `:375`, `:575`, `:427` |
| **The denylist silently drops real product companies.** `is_skipped_company()` docstrings "exact-name match" but does a **substring** test. Short entries eat legitimate names: `UST`→c**ust**omer.io, `Dice`→in**dice**s, `iGate`→nav**igate**, `Numero`→**numero**us. `Qualcomm` is simply a wrong entry. Drops happen before the AI runs, visible only in the drop log. | `stage1_scrape.py:274`; `settings.py:33,40,41,43` |
| **`_notion_write_job()` has three latent bugs**, each rediscovered by four of five plans: hardcodes `Status="Scraped"`; `if job.get("ats_score"):` discards a genuine `0`; bare `except: return None` turns any schema mismatch into an undiagnosable zero-row run. | `utils.py:312,315,319-320` |
| **Collected-then-discarded:** `applicant_count` and `salary_range` are parsed in stage 1 and passed to `db_add_job`, but `_notion_write_job` never writes them. `TARGET_COMPANIES` is referenced nowhere. | collected `:144-145`, passed `:594-595`; `settings.py:15` |
| **`APIFY_API_TOKEN` is a live plaintext literal** and is in git history. | `settings.py:142` |

### Corrections to the earlier analysis

Three claims in the prior draft of this README were stale or incomplete. They are fixed here:

1. **`ANTHROPIC_API_KEY` is not defined in `settings.py` at all.** Both `utils.py:13` and `run.py:55`
   read it via `getattr(_settings, "ANTHROPIC_API_KEY", "")`, falling back to `""`, and `_chat_claude`
   authenticates with that value (`utils.py:46`). So Plan 2's metered fast tier and Plan 5's CI
   provider split must **add** the key (env-sourced) to settings — not merely "move it to env." Without
   it, "route the fast tier to metered Haiku" silently has no credential.

2. **New finding no plan catches — the agentic status enum.** `workflow.py:196` defines `_STATUSES`,
   which is the `enum` backing the `get_jobs` / status-update tool schema (`:306`). Plan 1 asserts
   "`workflow.py` needs no change" and Plan 2 lists workflow changes, but **neither adds the new status**
   (`Retry` / `Needs Review`) to `_STATUSES`. Stage-1 writes set the status string directly, so the
   scrape path works — but the agentic path cannot filter or set the new status until it is added to
   that enum. Whichever status name wins (C3) must also land in `workflow.py:196`.

3. **`STAGE_AI_PROVIDER` already works as designed** (`utils.py:147-150`, `settings.py:131`) — a
   functioning per-path provider override, not dead scaffolding. Plan 2 supersedes it with `AI_ROUTING`
   deliberately; it is not filling a gap.

---

## Conflicts between the plans

Not flagged in the plans themselves. Ignoring them means writing the same code twice. All eight were
re-verified.

### C1 — Plans 1 and 2 both rewrite `score_jobs_batch()`, incompatibly

Both replace the same `except → score 50` block and change the return shape. They disagree on what
happens next:

| | Plan 1 | Plan 2 |
|---|---|---|
| On AI failure | fail open, write the job | fail open, write the job |
| Status written | `Needs Review` | `Retry` |
| Score | `None` + `scored: False` flag | `None` |
| Recovery | none — human reviews by hand | `rescore_retry_jobs()` re-scores from the cached JD, capped by `Scoring Attempts` |

Plan 2's failure model is strictly better: it recovers automatically, costs no Apify call (JD is
already cached in the page body), and bounds itself with an attempt cap. Plan 1's real contribution
is the *filter* logic, not the failure model. **Merge them: Plan 2's failure model + Plan 1's
filters.** Landing separately means one rewrites the other's ~60 lines.

### C2 — Plans 1 and 2 add retry at different layers

Plan 1 adds a separate `ai_chat_retry()` wrapper that raises. Plan 2 puts retry **inside**
`ai_chat()` with typed exceptions (`AIChatError`, `AIUsageCapError`) plus a usage-cap failover to the
metered API — covering all four `_BACKENDS` and every caller for free. Plan 1 even notes its helper
is the one "§1 wants for `stage3_outreach.py`" and proposes the weaker shape anyway. **Take Plan 2's.**

### C3 — Three names for one concept, none reusing the existing status

Plan 1 introduces `Needs Review`; Plan 2 introduces `Retry`; neither string appears in the codebase.
The documented schema already carries **`Human Review`** as a manual-only off-pipeline option. Pick
one before either lands — and add it to `workflow.py:196 _STATUSES` (see correction #2).

### C4 — Plan 5's dependency on Plan 1 is not satisfied by Plan 1

Plan 5 requires Plan 1 to extract a standalone `classify_company_type(companies) -> dict` out of
`score_jobs_batch()`. Plan 1 §4 **explicitly declines**: "Keep it a single combined call." As
written, Plan 1 leaves `company_type` welded to a prompt that needs a résumé and a JD and cannot
accept a bare company name. Plan 5 must either fund the extraction or fall back to
`is_skipped_company()` alone (its listed interim path).

### C5 — Plan 4 is built on the dead actor Plan 3 identified

Plan 4's `ENABLED_SOURCES` defaults to `["linkedin", "indeed", ...]`, and §1c says to "fix the Indeed
date bug by sending the actor's max-age param." **You cannot fix a date parameter on an actor that
404s.** Plan 4 also never engages Plan 3's central recommendation (JobSpy, free, self-hosted,
covering LinkedIn + Indeed + Glassdoor + Google Jobs in one call). This is the sharpest inconsistency
in the set; the Step-1 spike resolves it.

### C6 — Plan 3 makes Plan 5 substantially cheaper

Plan 5 notes it: `valig~linkedin-jobs-scraper` returns `recruiterName` + `recruiterUrl` with no
cookie, so **if the actor swap lands first, prong 1's job-linked contact data arrives free as a side
effect of scraping**, and the `coregent` lead actor is not needed for Mode A. Sequencing 3 before 5
removes a vendor.

### C7 — `_notion_write_job()` is modified by four plans

Plans 1, 2, 4, and 5 each add different properties to it and each independently proposes to fix the
same bare `except`. Only Plan 5 generalizes the writer (`db_id` param on `_query_db`,
`_notion_create_page`, `_safe_select`, propagate exceptions). Whoever touches it first should land the
**error-surfacing fix** once, for everyone — a schema mismatch currently manifests as a total scrape
outage with no diagnosable cause.

### C8 — One bug blocks two plans

The dedup self-match (Plan 2 §3.5) blocks Plan 2's own retry queue *and* Plan 4's fingerprint set — a
queued row would be dropped as a duplicate of itself on the next scrape. Plan 2 flags this; Plan 4
inherits the trap through `db_get_all_jobs()` without noticing.

---

## Scope-change answers (the two questions asked)

**Does implementing a plan push another out of scope?** Partially.

- **Plan 3's actor swap absorbs Plan 4's entire Indeed sub-task** — there is no Indeed date bug to fix
  once the 404'ing actor is replaced (C5).
- **Plan 3 pre-satisfies Plan 5's prong-1 lead source** — `valig`'s recruiter fields make the
  `coregent` lead actor *optional* for Mode A (C6).

**Does implementing a plan force another to change implementation?** Yes, three times.

- **Plan 2 forces Plan 1** to drop its `score_jobs_batch()` rewrite, its retry wrapper, and its status
  name (C1, C2, C3).
- **Plan 3's spike forces Plan 4** to re-key its source registry away from the dead actor (C5).
- **The batched schema migration (Step 2) forces Plans 1, 2, and 4** to write only to pre-existing
  properties — removing each plan's separate, individually-risky "add a Notion property" step.

---

## Recommended execution order

One independent prerequisite (**Step 0**); everything else is strictly sequential because each step
de-risks or unblocks the next.

### Step 0 — Rotate `APIFY_API_TOKEN` *(security incident, not a feature; do it now)*

`settings.py:142` is a live token in git history. Rotate it, move it to `os.environ.get`. Independent
of every plan, and it **must** precede Plan 5, which moves secrets into GitHub Actions.

### Step 1 — Sourcing spike *(resolves C5 and the JobSpy-vs-Apify fork)*

Run each actor once with `maxItems=3`, dump the raw dataset keys, and count the real listing volume.
Confirm whether the LinkedIn payload matches its actor. Output two things: (a) the actual Stage-1
baseline — currently unknown because Indeed has silently returned zero; (b) a decision between the
`valig` + `misceres` swap (Plan 3's Option A) and JobSpy.

*Why first:* Plans 1, 2, and 4 all tune filters, dedup, and scoring against a volume nobody has
measured. Plan 4 says so itself: *"the real baseline for what Stage 1 ingests is unknown."* A few
hours here de-risks four plans. **Nothing downstream is written until the spike returns.**

### Step 2 — Batched Notion schema migration *(up front, one pass)*

Add all new properties by hand, before any writer code, so a mismatch never causes a silent outage:
`Sponsorship` (select: yes/no/unknown), `Scoring Attempts` (number), `Posted Date` (date), `Source`
(**rich_text**, not select — an un-pre-created select option throws on write), `Applicant Count`
(number), `Salary Range` (rich_text), and the C3 status option on `Status`. Then land the
**`_notion_write_job` error-surfacing fix** (C7) so the *next* mismatch is diagnosable. This one
migration removes the risky manual step from Plans 1, 2, and 4.

### Step 3 — Dedup self-match fix *(Plan 2 §3.5, ~10 lines, unblocks C8)*

Give `db_find_job_by_url()` an `exclude_page_id` parameter; narrow the `existing_urls` snapshot
(`stage1_scrape.py:541`) to exclude `Interested`/new-status rows. Fixes manual intake **today** and
unblocks both Plan 2's retry queue and Plan 4's fingerprint dedup. While here, fix
`scrape_job_urls()`'s silent `{}` return so a failed enrichment and an empty one don't look alike.

### Step 4 — Plan 1a, the pure-function half *(first user-visible feature)*

Word-boundary company matching (`_tokens`, `_strip_suffix`, `_subseq`), drop `Qualcomm`, and
`_jd_excerpt(head=1200, tail=800)` so the model finally sees the work-authorization block at the
*bottom* of a JD. Pure functions, offline-unit-testable, no schema change, no AI call. **Highest
value-per-line in the directory, and it directly answers the user's two complaints.** *Hold Plan 1b —
everything touching `score_jobs_batch()` — until Step 5.*

### Step 5 — Merge Plan 2 + Plan 1b *(resolves C1/C2/C3)*

Adopt Plan 2's `Retry` failure model, in-`ai_chat` retry with typed errors, and metered failover;
adopt Plan 1's `company_type` classification and `Sponsorship` write; settle **one** status name and
**add it to `workflow.py:196 _STATUSES`** (correction #2). Add the env-sourced `ANTHROPIC_API_KEY` to
settings (correction #1). Decide C4 now: extract `classify_company_type()` as a standalone so Plan 5
reuses it, or record that Plan 5 uses `is_skipped_company()` alone.

### Step 6 — Plan 4, Phase 1 only *(free ATS boards)*

Greenhouse, Lever, Ashby: free, unauthenticated, real posted dates, full JD (cleaner Stage-2 input
than a LinkedIn blob). They structurally exclude staffing firms, which don't post client roles on
their own boards. `TARGET_COMPANIES` finally gets a consumer. **Hold Phase 2** (~$15/mo + Glassdoor/
Wellfound anti-detect-browser ToS posture). Reconcile C5 using Step 1's decision.

### Step 7 — Plan 5 *(most complex; last)*

Only after its **Phase-0 spike** returns — four live unknowns gate the design (Hunter inline
`verification.status`, free-tier `linkedin_handle` support, billing edges, coregent field map). It is
the only plan that changes *how and where the pipeline runs*: GitHub Actions, forced provider split,
new Leads DB, two new vendors. Benefits from Step 1 (C6) and Step 5 (C4).

### Independent vs. sequential

- **Independent — slot anywhere:** Step 0 (token rotation); the `save_draft()` `encoding="utf-8"` fix
  (`stage3_outreach.py:140`, a latent Windows cp1252 crash on real human names).
- **Strictly sequential:** 1 → 2 → 3 → 4 → 5 → 6 → 7. Each de-risks or unblocks its successor; the
  order is not arbitrary.

---

## Complexity ranking

Ranked by blast radius, new surface area, external dependencies, and unresolved unknowns.

| Rank | Plan | Why |
|---|---|---|
| **1 — most complex** | **5 · Communications** | Two new stages, a new Notion database (~22 props), new `scripts/credits.py`, a digest refactor, two new vendors (Hunter.io, coregent), and a new execution model (GitHub Actions — which forces the provider split, kills the SQLite ledger on ephemeral runners, and strands `output/`). Adds headless Gmail OAuth, GDPR obligations, a credit budget, and a human approval gate. A blocking Phase-0 spike precedes any code. Depends on Plan 1 (C4), benefits from Plan 3 (C6). |
| 2 | **4 · Multi-source** | New `scripts/sources.py`, two registries, a `run()` restructure from per-role scoring to global gather → collapse → filter → score. Unequal ATS slug-collision risk (Greenhouse verifiable, Lever/Ashby not). Four Notion props. Phase 2 adds real spend and ToS exposure. Built on the dead actor (C5). |
| 3 | **2 · Reliability** | Touches `settings.py`, `utils.py`, `stage1_scrape.py`, `workflow.py`, `run.py`. Provider tiering + typed exceptions + usage-cap failover + a capped retry queue + two schema props. Intricate but contained. Holds the one blocking bug (§3.5) and reintroduces metered cost. |
| 4 | **1 · Filtering** | Confined to `stage1_scrape.py`, `utils.py`, `settings.py`. One Notion prop. Core is pure functions with offline tests. Only real hazard is the `score_jobs_batch()` collision with Plan 2 (C1). |
| **5 — least complex** | **3 · Sourcing** | Not an implementation plan. Its actionable core is two actor constants and two payload builders — the smallest diff in the directory, and the one that de-risks the most other work. |

**Most complex: Plan 5. Implement first: Step 1's spike, then the schema migration, then Plan 1a** —
the first change the user sees.

---

## Cost summary

| Change | Δ monthly |
|---|---|
| Drop the `bebity` LinkedIn rental (Step 1 / Plan 3) | **−$29.99** |
| `valig` LinkedIn + `misceres` Indeed, at current volume | ~+$0.50 |
| Plan 2 fast tier → metered Haiku | +$3–5 |
| Plan 4 Phase 1 (ATS boards) | $0 |
| Plan 4 Phase 2 (four Apify sources, daily) | +$15 |
| Plan 5 (Hunter free tier; Apify Mode A) | ~+$0.02, or +$9 with Mode B |

Steps 0–5 land **net cheaper than today**.

---

## Open questions

Answers change the plans; none block Steps 0–3.

1. **Status naming (C3).** `Retry`, `Needs Review`, or reuse the existing `Human Review`? One name —
   and it must also land in `workflow.py:196 _STATUSES`.
2. **JobSpy vs. Apify (C5, Step 1).** The spike resolves it, but a pre-stated lean helps. `valig` +
   `misceres` is the smallest diff and hands Plan 5 free recruiter fields; JobSpy is free and covers
   more boards but rate-limits on LinkedIn without proxies and ships slowly.
3. **`classify_company_type()` extraction (C4).** Fund the standalone in Step 5 so Plan 5 reuses it,
   or let Plan 5 rely on `is_skipped_company()` alone?
4. **Indeed at all?** Zero listings for the life of the project — fix it, or drop it from
   `ENABLED_SOURCES`?
5. **Plan 4 Phase 2 ToS posture.** Glassdoor and Wellfound prohibit scraping and the actors advertise
   anti-detect browsers. Acceptable, or stop at the three free ATS boards?
6. **GitHub Actions (Plan 5).** Adopting CI means scheduled runs bill metered tokens and can no longer
   use the subscription. Accept, or keep everything local and manual?
7. **`Sponsorship` semantics.** Keep `unknown` jobs and surface them? The regex only catches postings
   that *explicitly* deny sponsorship, so `unknown` will be the large majority.
