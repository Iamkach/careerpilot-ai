# Communications subsystem — LinkedIn leads + verified cold email

*Absorbs and replaces the earlier `networking-sourcing.md` draft (never committed; covered only the LinkedIn prong).*
*Corrects and supersedes §3 of the former `plan/reliability-filtering-networking.md`, removed in `63b64e7` —
read it with `git show 1030d71:plan/reliability-filtering-networking.md`. Baseline: `feat/maverick` @ `3f91db7`.*
*See [`../README.md`](../README.md) for how this plan relates to the other four.*

## Context

Two prongs, one subsystem:

1. **LinkedIn** — find the people attached to live reqs (job poster, recruiter, hiring manager), keep them as durable
   Leads with company/team/status, and draft targeted outreach behind a manual approval gate.
2. **Cold email** — for top-ATS jobs, identify who is actually worth contacting — the hiring manager, the team's lead,
   a would-be peer, or a plausible referrer — then resolve a **verified** professional email via Hunter.io.

Both feed the daily digest and run on a schedule, so the search becomes proactive rather than manual.

**The governing rule, from the user, and it drives the whole architecture:** never invent, guess, or pattern-match a
person or an email. If Hunter can't confirm it, we don't have it — fall back to the LinkedIn profile and flag it.

That rule has a clean architectural expression: **APIs supply facts; AI ranks and writes.** AI never produces a name,
a title, an email address, or a domain. It selects among real people returned by an API, and it drafts prose. This is
enforced by a code-level validator, not by trusting the prompt.

Today there is **no scheduling infrastructure of any kind**, no contact data source, no Leads store, and no digest
section primitive. This is largely greenfield.

---

## What §3 of the reliability plan got right (verified against the code)

- Zero contact-acquisition capability. Both Apify actors are job-listing scrapers (`stage1_scrape.py:36,38` — **not** `settings.py:36,38` as §3 cites).
- `LINKEDIN_SESSION_COOKIE` is used exactly once, in `_linkedin_payload_base()` (`stage1_scrape.py:86`), purely to enrich listings.
- `_draft_inmail_single(job, bio)` (`stage3_outreach.py:277`) takes no contact name.
- `draft_warm_referral()`'s `contact_name` (`stage3_outreach.py:36`) reaches it only from a human-typed `--contact` flag — every call path terminates there.
- The `Hiring Manager` / `Hiring Manager LinkedIn` Notion properties are a **dead write path**: `_EXTRA_TO_NOTION` maps them (`utils.py:327-328`) but no caller ever passes them.
- No Leads database exists. `NOTION_DB_ID` (`settings.py:146`) is the only database id.
- The ToS caution is correct, and is the reason for the redesign below.

## What §3 got wrong (each changes the work)

1. **"A drop-in third actor rather than new plumbing" is false.** `_apify_run()` (`stage1_scrape.py:47-72`) is
   genuinely actor-agnostic and reusable — but it is ~25 lines of a much larger job. Every `db_*` helper bakes
   `NOTION_DB_ID` in as a module global, not a parameter: `_query_db` hardwires `{"database_id": NOTION_DB_ID}`
   (`utils.py:433`) and `_notion_write_job` hardcodes the jobs schema plus `Status="Scraped"` (`utils.py:300-320`).
   A Leads database is an **entirely new write/query layer**.

2. **The pattern §3 wants to copy is the bug.** §3 justifies reuse by saying the existing actors "were presumably
   vetted." That was wrong: `bebity~indeed-scraper` **returned HTTP 404** and had silently contributed zero
   listings on every run, hidden by `except Exception: return []` (now fixed — see `../../CHANGELOG.md` Step 1).
   If the new stage copies that swallow, a broken actor reads as "nobody is hiring." **A failed run and an empty
   run must never look alike.**

3. **§3 has an undeclared dependency on §2 that §2 does not deliver.** §3 says to reuse "the new `company_type`
   classification." That lives inside `score_jobs_batch()` (`stage1_scrape.py:322-381`), whose prompt is built around
   résumé + JD + ATS score and cannot accept a bare company name. §2 must factor it out before this can reuse it.

4. **The "no extra API call" saving does not transfer.** §2a adds a field to a batched call that *already happens*.
   Leads have no such call to piggyback on. As it turns out we don't need one — the chosen actor classifies for us.

5. **Cost is unanalyzed.** §3 mentions none, while the sibling sourcing plan budgets carefully. Sizing is below.

6. **"Rate-limit aggressively" is not actionable.** `_apify_run()` issues one actor run, not a request loop; rate
   limiting is actor-side. The real volume levers are `maxResults` and run cadence.

---

## The correctness gap that shapes the design

`coregent`'s actor returns the **job poster**, which is usually a *recruiter*. Prong 2 explicitly wants the hiring
manager, team lead, plausible peer, or referrer. **These are different personas, and one does not substitute for the
other.** The naive design — "reuse prong 1's person for prong 2's email" — quietly cold-emails the recruiter and
labels them a hiring manager.

Resolution: reuse the coregent person for prong 2 only when they are a genuine direct poster (`is_direct_job_poster`)
and not recruiter-like. Otherwise discover hiring-manager-like people via Hunter **Domain Search** with
`seniority` / `department` filters. Persona is recorded explicitly on every lead.

---

## Sources: chosen and rejected

Researched per the instruction not to assume Apify.

| Source | Verdict |
|---|---|
| **Hunter.io** — Email Finder, Email Verifier, Domain Search | **Core.** Domain Search returns *people* (`first_name`, `last_name`, `position`, `seniority`, `department`, `linkedin`, `confidence`, `verification`), not just addresses, and accepts a `company` name. It covers prong 2 end-to-end with no scraping. |
| **Apify `coregent~linkedin-recruiter-job-poster-finder`** | **Core, narrow.** Uses LinkedIn's *public guest* job endpoints — no `li_at` cookie, so ban risk lands on the actor's proxies, not your account. ~$2.40/1k unique leads; person-less jobs and duplicates are not billed. It is the only viable way to learn who posted a *specific* req. |
| `apt_marble~linkedin-recruiter-scraper` | **Fallback only.** $1.50/1k, also no-cookie, but returns recruiters *unattached* to a specific job — no `job_url`, so no join onto the jobs table. Prefer coregent. |
| Apollo.io | **Rejected.** People Search is free and credit-less, but the free tier **obfuscates `last_name`**, which breaks Hunter's Email Finder (it needs a full name). Emails require credits regardless. |
| People Data Labs | **Rejected.** 100 lookups/mo and **email fields restricted on free access**. |
| Clearbit enrichment | **Rejected.** Free tier sunset April 2025. Its keyless *autocomplete* endpoint is used opportunistically for company→domain but never depended on. |
| Proxycurl | **Rejected.** Shut down July 2025. |
| Scraping LinkedIn's guest endpoint ourselves with `requests` | **Rejected.** Brittle, IP-blocked, and a worse ToS posture than paying a vendor that absorbs it. |

Apify is not eliminated — it is reduced to the one job it alone can do.

> **Already landed (see `../../CHANGELOG.md` Step 1):** LinkedIn sourcing was swapped to
> `valig~linkedin-jobs-scraper` on cost grounds ($0.28–0.40/1k vs. the old $29.99/mo bebity rental). That actor
> returns `recruiterName` + `recruiterUrl`, no cookie — **prong 1's job-linked contact data arrives free as a
> side effect of scraping, with no second actor needed.**

---

## Decisions (binding)

- **No authenticated LinkedIn scraping.** §3 assumed people/post search, which requires an `li_at` session cookie and
  risks restriction of *your* account — the very account whose network the feature exists to leverage. Dropped in
  favor of public, unauthenticated endpoints.
- **Hunter free tier, budget-gated.** 50 credits/month. Email Finder = 1 credit per email *found* (no charge when not
  found); Verifier = 0.5. Requires a credit ledger, a daily/monthly budget, and a priority queue ordered by ATS score.
  Repeats are counted once per calendar month, so caching is genuinely free.
- **`accept_all` policy.** Many large product companies run catch-all domains, where SMTP cannot confirm a specific
  mailbox exists. Record the address **only** when Hunter itself returned it (never constructed from Hunter's
  `pattern` field) **and** `score ≥ ACCEPT_ALL_MIN`. Persist `Email Status = accept_all` with the verbatim score and
  `Verified = false`. The digest renders it as *"unverified — send at your discretion."* It never counts as verified.
- **Scheduling: GitHub Actions** (cron), with **`workflow_dispatch` for manual runs** and the local agentic
  orchestrator (`python workflow.py --task …`) remaining fully usable by hand. See *Execution environments* below —
  this choice has three consequences that reshape the design.

---

## Architecture

```
stage1 scrape ──→ Notion Jobs DB
                        │
        ┌───────────────┴────────────────┐
        ↓ (prong 1, Apify)               ↓ (prong 2, Hunter)
  stage7_leads_discover           stage8_email_resolve
  coregent job-poster              priority queue (ATS desc)
  is_skipped_company filter        budget gate ← Hunter /v2/account (free)
  AI: rank persona (by index)      domain chain → Email Finder
        │                          accept_all / valid / none policy
        └──────────→ Notion Leads DB ←──────────┘
                        │  Outreach Status = Drafted
                        │        ↓ human sets Approved (the gate)
                        ↓
              stage3 drafters  →  output/outreach/
                        ↓
              stage4 digest (new sections)
```

**"Parallel cron" is a red herring worth naming.** The two prongs hit different external quotas (Apify vs. Hunter) and
neither is CPU-bound; Hunter's free budget allows roughly *one person per day*. Separate jobs are still the right shape
— they retry and re-run independently — but the thing that actually needs designing is **shared state** (the budget
and the Leads upsert), not throughput.

---

## Execution environments

Two hosts run the *same* stage scripts. Nothing forks; only the sequencer and the provider differ.

| | **GitHub Actions** (scheduled + `workflow_dispatch`) | **Local** (manual, agentic) |
|---|---|---|
| Entry point | `python run.py --stage N` | `python workflow.py --task …` |
| AI provider | `claude` (metered, `ANTHROPIC_API_KEY`) | `claude_code` (subscription) |
| Secrets | GitHub Secrets → env | local env |
| Filesystem | **ephemeral** | durable |

Choosing GitHub Actions forces three changes. Each is load-bearing.

### 1. The provider split stops being optional

`AI_PROVIDER = "claude_code"` (`settings.py:125`) drives everything through the Agent SDK, which requires an
interactive `claude /login` session. **That cannot exist on a GitHub runner.** CI must run `AI_PROVIDER="claude"` with
a metered `ANTHROPIC_API_KEY`.

This is exactly the split §1 of `reliability-filtering-networking.md` recommends, and the plumbing already half-exists:
`STAGE_AI_PROVIDER` (`settings.py:131`) is there for this purpose, and `workflow.py:34` already strips
`ANTHROPIC_API_KEY` from the environment unless `AI_PROVIDER == "claude"`. Two changes needed:

- `settings.py:125` becomes `AI_PROVIDER = os.environ.get("AI_PROVIDER", "claude_code")` — local behavior unchanged,
  CI overrides via env.
- CI sets `AI_PROVIDER=claude` + `ANTHROPIC_API_KEY`. Local keeps the subscription and never sets that key.

Scheduled runs stop depending on a login session staying alive, and stop being killable by a subscription usage cap —
which is the failure §1 was written to fix.

### 2. Ephemeral runners kill the SQLite credit ledger — replace it with Hunter itself

A local SQLite ledger cannot survive a runner that is destroyed after each job. `actions/cache` is evictable and would
silently lose spend history; committing a binary DB back to the repo invites races. All wrong for a spend counter.

**`GET https://api.hunter.io/v2/account` is free of charge** and returns the plan, credits used, remaining quota, and
the reset date — separately for searches and verifications. That is authoritative, real-time, Hunter-side truth. It
cannot drift, cannot double-spend, and needs no local state at all. Query it before draining the queue; stop when the
remaining quota hits the reserve floor.

The rest of the ledger collapses accordingly:

- **Mutual exclusion** → a GitHub Actions `concurrency:` group on the Hunter job. Replaces `BEGIN IMMEDIATE`.
- **Query cache** → Hunter already counts a repeated identical search once per calendar month, so caching is an
  optimization, not a correctness requirement. `Last Hunter Attempt` and `Email Status` on the Notion lead row (both
  already in the schema) are durable and sufficient.
- **Company→domain cache** → `config/company_domains.json`, committed. Small, text, reviewable, survives the runner.

`scripts/credits.py` shrinks from a transactional SQLite store to a thin budget guard over `/v2/account` plus a JSON
domain cache. This is a strictly simpler design that the host change forced into view.

### 3. Ephemeral filesystem means outputs must leave the runner

`output/outreach/*.txt` and the digest HTML vanish when the job ends. Drafts are written into the **Notion lead page
body**, mirroring how `db_add_job` already caches the job description in the job page body — durable, and it is where
the human reviews and approves anyway. Workflow artifacts are uploaded as a secondary copy. The digest still sends via
Gmail.

**Gmail OAuth needs care.** `send_via_gmail` (`stage4_digest.py:191`) loads an installed-app OAuth credential from
`GMAIL_CREDENTIALS_PATH`, whose consent flow opens a browser — impossible headless. Do the consent **once locally**,
then store the resulting refresh-token JSON as a GitHub Secret and materialize it to that path at job start. If that
proves fiddly, ship CI with `--send` off and read the digest from the artifact until it's wired.

### Secret rotation is now mandatory, not advisory

`APIFY_API_TOKEN` is a committed plaintext literal (`settings.py:142`) and is in git history. Moving automation onto
GitHub does not expose it any further — **it is already exposed** — but it must be rotated and made env-only before
any workflow references it. Same pattern for `NOTION_API_KEY` (already `os.environ.get`), `HUNTER_API_KEY`, and
`ANTHROPIC_API_KEY`.

---

## Phase 0 — Blocking spike (throwaway script, settles four unknowns)

Nothing downstream is written until this returns. Each item is a real unknown, not a formality.

1. **Does Email Finder return a terminal `verification.status` inline, or `pending`/`null`?** Hunter's verification is
   reportedly asynchronous. If terminal, **the Verifier is never needed** and capacity stays ~50 people/month. If
   pending, call the Verifier (0.5 cr) *only* for non-terminal statuses — blanket verification would cut capacity from
   ~50 to ~33 for no correctness gain. **This decides the verification policy; do not code it before knowing.**
2. **Does the free tier honor Email Finder's `linkedin_handle` param?** If yes, a coregent profile URL feeds Hunter
   directly and company→domain resolution is skipped entirely — the cheapest path in the system.
3. **Confirm the billing edges:** not-found = 0 credits; what an `accept_all` hit costs.
4. **Is Clearbit's keyless autocomplete still up?** And run coregent against 1–2 real Notion jobs with `maxResults=3`:
   inspect the raw dataset keys and **write the field map against real output, never the vendor docs**, and confirm
   person-less jobs aren't billed.

## Phase 1 — Foundations (zero spend)

- **`scripts/credits.py` (new)** — a thin budget guard, **not** a ledger (see *Execution environments* §2). Wraps the
  free `GET /v2/account` for authoritative remaining quota, exposes `remaining()` / `can_spend(n)` / `reserve_floor`,
  and owns `config/company_domains.json` as a committed domain cache. No SQLite, no local spend log: Hunter is the
  source of truth, and the Actions `concurrency:` group provides mutual exclusion.
- **`scripts/utils.py`** — add `_notion_create_page(db_id, props)` and `_notion_query(db_id, filter)`, plus a `db_id`
  param defaulting to `NOTION_DB_ID` on `_query_db` (`utils.py:429-446`, currently hardwires the database id).
  Build `db_add_lead()` / `db_get_leads(status)` / `db_update_lead_status()` on top. **These new helpers must let
  exceptions propagate.** `_notion_write_job`'s bare `except` (`utils.py:300-320`) is exactly why a schema mismatch
  surfaces as an undiagnosable zero-row run. Add `_safe_select(value, allowed, default)` — a `select` value that isn't
  a pre-created option throws on write, and that bare except swallows it.
- **`config/settings.py`** — `HUNTER_API_KEY = os.environ.get(...)`, `NOTION_LEADS_DB_ID`, budget constants, score
  thresholds, `LEAD_ACTOR`, `LEAD_MIN_RELEVANCE = 60`, `LEAD_DISCOVERY_MODE = False`.
  **`APIFY_API_TOKEN` is currently a committed plaintext literal (`settings.py:142`) and is in git history — rotate it
  and move it to env. Do not repeat that pattern for the Hunter key.**
- Create the Leads DB and **pre-create every select option by hand** before any writer runs.

## Phase 2 — Prong 1: `scripts/stage7_leads_discover.py` (new)

Two acquisition modes; the actor accepts both input shapes.

| Mode | Input | Cost per run | Use |
|---|---|---|---|
| **A — job-linked** | `job_url`s already in Notion (`Status = Reviewed`) | ~5–10 leads ≈ **$0.02** | Default. Precise, nearly free, joins onto rows you already care about. |
| **B — discovery** | `TARGET_ROLES` × `TARGET_COMPANIES` keywords | ~125 leads ≈ **$0.30** (~$9/mo daily) | Opt-in, off by default. Finds leads at target companies with no live reviewed posting. |

Mode A also finally gives `TARGET_COMPANIES` (`settings.py:15`, currently dead config) a consumer.

- Call `_apify_run(LEAD_ACTOR, payload)` (`stage1_scrape.py:47-72`) — genuinely actor-agnostic, reuse as-is.
- **Let it fail loudly.** Do *not* copy `scrape_indeed`'s `except Exception: return []` (`stage1_scrape.py:166-170`).
  A failed run exits non-zero; a run that found nobody exits 0 with a "0 leads" log.
- Filter recruiters at staffing firms through `is_skipped_company()` (`stage1_scrape.py:265-279`, a pure name check).
  Drop rows below `LEAD_MIN_RELEVANCE` (60 — the actor's "Medium" band).
- **§3's poster-role classification is already done** by the actor (`is_recruiter_like`, `is_direct_job_poster`, a
  rule-based `relevance_score`). §3's "regex first pass, LLM fallback" is unnecessary — cut from scope.
- Dedup on `linkedin_profile_url` against a single `db_get_leads()` snapshot, mirroring stage 1's in-memory URL-set
  pattern rather than querying Notion per lead. Upsert keyed on that URL so re-runs are idempotent across processes.
- Reuse `_open_drop_log` / `_log_drop` (`stage1_scrape.py:444-467`) with reasons `company`, `low-relevance`,
  `duplicate`, `no-profile-url`.

**§2 dependency:** if §2a's `company_type` AI classification is wanted here, §2 must extract it from
`score_jobs_batch()` into a standalone `classify_company_type(companies) -> dict`. Until then, use
`is_skipped_company()` alone. Do **not** re-implement the classifier here — that is precisely the drift `CLAUDE.md`
warns against.

## Phase 3 — Prong 2: `scripts/stage8_email_resolve.py` (new)

Priority queue over top-ATS jobs, drained until the daily/monthly budget is exhausted; the remainder stays queued at
`Outreach Status = Ranked` and the process exits 0. The queue backing up in ATS order is the desired behavior.

**Domain resolution chain, cheapest first, every outcome cached in `config/company_domains.json`:**

1. `linkedin_handle` on Email Finder → **domain resolution not needed at all.** Preferred whenever a profile URL exists.
2. `company_domains.json` cache hit → free.
3. The job's own apply/ATS URL already in Notion → free, no vendor.
4. Clearbit autocomplete (keyless) → free but unofficial; any failure or timeout means "unresolved," never a blocker.
5. **Never use Hunter Domain Search merely to get a domain** — it bills 1 credit per email returned. It is a
   person-discovery tool (prong 2's hiring-manager search via `seniority`/`department`), not a domain resolver.

If 1–4 all fail: no domain → no Email Finder call → LinkedIn fallback + "no verified email." **Never guess a domain.**

**Email policy** (pending the Phase 0 spike):

| Hunter result | Action |
|---|---|
| `valid`, `score ≥ VALID_MIN` | Record. `Verified = true`. |
| `accept_all`, address returned, `score ≥ ACCEPT_ALL_MIN` | Record. `Verified = false`, `Email Status = accept_all`, score verbatim, digest note *"unverified — send at your discretion."* |
| `invalid` · `webmail` · `disposable` | No email. LinkedIn fallback + flag. |
| `unknown` / `pending` / `null` | One Verifier call (0.5 cr); re-apply this table. Still unknown → no email + flag. |

**Hunter's `pattern` field (e.g. `{first}.{last}`) is display-only and must have no code path into the Email
property.** This is the literal encoding of "never pattern-match," and it gets its own unit test.

## Phase 4 — AI, and the approval gate

**AI does exactly two jobs, both over real API output.**

*Rank the contacts.* Reuse `ai_chat(..., quality=True)` + `parse_json_response()` (`scripts/utils.py`).

- In: `{"job": {title, company}, "candidates": [{"idx", "name", "title", "seniority", "department", "linkedin"}]}`
- Out: `{"ranked": [{"idx", "persona": "hiring_manager|team_lead|peer|referrer|recruiter", "worth_contacting", "priority", "reason"}]}`
- **The guardrail is code, not the prompt.** After parsing, validate every returned `idx` against the input set and
  drop anything referencing a name or email not present in it. The system prompt says "select and rank *by index*; you
  MUST NOT invent names, titles, emails, or domains" — but the validator is what enforces it.

*Draft the message.* Feed verified facts to the existing drafters. `draft_warm_referral()` (`stage3_outreach.py:36-48`)
is already contact-aware; add `draft_connection_request(lead)` modeled on it. This finally wires two dead code paths:
`_draft_cold_email_single`'s `hm_name`/`hm_context` (`stage3_outreach.py:109`, whose only caller passes neither, so the
`hm_line` renders as a bare `- ` bullet) and the `hiring_manager` / `hiring_manager_linkedin` mappings in
`_EXTRA_TO_NOTION` (`utils.py:327-328`, never written). `stage5_interview_prep.py:150` already reads `job["hm_li"]`
and lights up for free.

Also fix `save_draft()` (`stage3_outreach.py:140`): `.write_text(content)` has no `encoding=`, a latent Windows cp1252
crash that real human names make near-certain. Add `encoding="utf-8"`.

**The gate:** leads reach `Drafted` only after a human sets `Approved` in Notion. Nothing auto-advances to `Sent`.
No automated connecting or messaging, ever. `Drafted` exists so that re-running the drafter does not re-draft every
approved lead.

## Phase 5 — Digest (`scripts/stage4_digest.py`)

Today: two monolithic f-string builders (`build_html_digest:37`, `build_html_review_digest:92`) duplicating the whole
`<style>`/`<table>` scaffolding with `{{ }}`-escaped CSS. There is no section primitive, so a new section means forking
a third builder. Minimal refactor:

1. Hoist the shared CSS into a plain module constant `_DIGEST_STYLE` — a normal string, not an f-string, which removes
   the `{{ }}` doubling entirely.
2. Add `render_html_section(title, headers, rows, notice="")`, `render_plain_section(...)`, and `build_html_page(sections)`.
3. Re-express the existing two digests as sections (behavior-preserving), then add **LinkedIn Leads** and
   **Cold Email Contacts**. The latter renders `valid` rows normally, `accept_all` rows with the unverified note, and
   no-email rows as a LinkedIn URL plus a visible "no verified email" flag.

`send_via_gmail(html, plain, subject)` (`stage4_digest.py:191`) is already generic — reuse untouched.

## Phase 6 — Wiring, scheduling, and manual runs

**Local agentic path (unchanged, must keep working).** `workflow.py`: add `run_leads_discover` and `run_email_resolve`
to **both** `_TOOL_IMPL` (`184-194`) and `TOOLS` (`201-319`) — `_make_tool` does `_TOOL_IMPL[t["name"]]`, so a missing
entry is a `KeyError` at import. `_SDK_TOOLS`, `_SERVER`, and `_ALLOWED` (`343-348`) regenerate automatically. Add a
read-only `get_leads` (bypasses `_STAGE_LOCK`, like `get_jobs`), plus `_TASK_BUILDERS` entries so
`python workflow.py --task leads` and `--task emails` work at the keyboard under the `claude_code` subscription.

**Scheduled path.** One workflow, `.github/workflows/communications.yml`, with three jobs and `workflow_dispatch` so it
can also be triggered by hand from the GitHub UI:

```yaml
on:
  schedule: [{ cron: "0 13 * * 1-5" }]   # UTC; weekdays
  workflow_dispatch:
concurrency:
  group: communications                   # replaces the SQLite lock
  cancel-in-progress: false
```

| Job | `needs` | Quota | Notes |
|---|---|---|---|
| `discover_leads` | — | Apify | `python run.py --stage 7` |
| `resolve_emails` | `discover_leads` | Hunter | budget-gated via `/v2/account`; exits 0 when quota is spent |
| `digest` | `resolve_emails` | Gmail | uploads `output/` as an artifact |

Sequential, deliberately. Running `resolve_emails` in parallel with `discover_leads` would only ever operate on the
previous day's leads, and Hunter's ~1-person/day budget means parallelism buys no throughput. Independent *jobs* still
give what actually matters: per-step logs, retries, and re-runs.

Every job sets `AI_PROVIDER=claude` and pulls `ANTHROPIC_API_KEY`, `NOTION_API_KEY`, `HUNTER_API_KEY`, `APIFY_API_TOKEN`
from GitHub Secrets. Note that GitHub's `schedule` trigger is best-effort and can be delayed under load — fine for a
daily job, not something to build a tight SLA on.

---

## Notion Leads DB

New database; `NOTION_LEADS_DB_ID` in settings. One schema covering both prongs.

`Name` (title) · `Lead Title` · `Company` · `Team` · `LinkedIn URL` (url) · `Linked Job` (relation → Jobs DB) ·
`Job Title` · `Job URL` (url) · `Prong` (select: `linkedin`, `cold_email`) · `Source` (select: `coregent`,
`hunter_domain_search`, `manual`) · `Persona` (select: `hiring_manager`, `team_lead`, `peer`, `referrer`, `recruiter`) ·
`Is Direct Job Poster` (checkbox) · `Is Recruiter-like` (checkbox) · `Relevance Score` (number) ·
`Reason Tags` (multi_select) · `Email` (email) · `Email Status` (select: `valid`, `accept_all`, `none`) ·
`Email Score` (number) · `Verified` (checkbox) · `No Verified Email` (checkbox) · `Email Note` ·
`Outreach Status` (select) · `Draft Link` · `Last Hunter Attempt` (date)

**`Outreach Status` lifecycle** — one enum serving both prongs; the channel is captured by `Prong`:

```
New → Ranked → Approved → Drafted → Sent → Replied → Connected     (+ Skipped)
                  ↑ the human gate                ↑ human-confirmed
```

**Pre-create every select option by hand.** Notion rejects an unknown option, and the existing bare `except` turns
that into a silent no-op.

---

## Files

| File | Change |
|---|---|
| `scripts/credits.py` | **New.** Budget guard over Hunter's free `/v2/account`; owns `config/company_domains.json`. |
| `scripts/stage7_leads_discover.py` | **New.** coregent → filter → AI persona rank → Leads upsert. Loud failure. |
| `scripts/stage8_email_resolve.py` | **New.** Priority queue, budget gate, domain chain, Hunter policy, fallback flag. |
| `scripts/utils.py` | `db_id` param on `_query_db`; `_notion_create_page`, `_notion_query`, `_safe_select`; `db_add_lead` / `db_get_leads` / `db_update_lead_status`; write drafts to the lead page body; propagate Notion errors. |
| `scripts/stage3_outreach.py` | `draft_connection_request`; wire `hm_name`/`hm_context`; `encoding="utf-8"` on `save_draft`. |
| `scripts/stage4_digest.py` | `_DIGEST_STYLE` constant, section primitives, two new sections. |
| `config/settings.py` | `AI_PROVIDER` from env; `HUNTER_API_KEY` (env), `NOTION_LEADS_DB_ID`, `LEAD_ACTOR`, budgets, thresholds; rotate `APIFY_API_TOKEN` out of the literal. |
| `config/company_domains.json` | **New.** Committed company→domain cache. |
| `workflow.py` | Two new tools + read-only `get_leads`; `_TASK_BUILDERS` entries for `--task leads` / `--task emails`; `_TOOL_IMPL` and `TOOLS` in sync. |
| `.github/workflows/communications.yml` | **New.** Cron + `workflow_dispatch`; three sequential jobs; `concurrency` group; artifact upload. |
| `CLAUDE.md` | Document stages 7–8, the Leads DB, the gate, the credit budget, and the CI-vs-local provider split. |

---

## Verification

1. **Loud failure.** Point the actor id at garbage → the stage exits non-zero and writes nothing. Contrast with an
   empty-but-successful run → exit 0, "0 leads." Same for Hunter 401/429. *This is the regression test for the
   dead-Indeed-actor class of bug.*
2. **Notion schema first.** Create the DB by hand before deploying the writer. Then rename one property and confirm
   the new code reports the real Notion exception rather than silently writing nothing.
3. **`accept_all` policy.** Synthetic Hunter responses: (a) `accept_all` + score ≥ threshold + address present →
   persisted, `Verified=false`, digest shows the unverified note; (b) score < threshold → no email; (c) **only
   `pattern` present, no address returned → the Email property stays empty.**
4. **Never-pattern-match guardrail.** Unit test proving `pattern` has no code path to the Email property, and that the
   AI validator drops any returned index, name, or email absent from the API input set.
5. **Credit budget.** Set the reserve floor so only 2 credits are spendable, enqueue 5 jobs → ≤2 spent, 3 remain
   `Ranked`, and a follow-up `/v2/account` call reflects the spend. Re-run the same query in the same calendar month →
   Hunter charges **0**.
6. **CI parity.** Trigger the workflow via `workflow_dispatch` with `AI_PROVIDER=claude`; confirm the stages run with no
   `claude /login` session present, and that the same stage run locally under `claude_code` produces equivalent output.
   Confirm `ANTHROPIC_API_KEY` is absent from the local environment (`workflow.py:34` strips it, but verify).
7. **Ephemeral-output safety.** After a CI run, confirm every draft is readable in the Notion lead page body — not only
   in the uploaded artifact.
8. **Filters.** A staffing-firm recruiter (company matching `SKIP_COMPANY_KEYWORDS`) is dropped with reason `company`
   in `output/filter_logs/`. A `relevance_score` of 40 is dropped as `low-relevance`.
9. **The gate holds.** Run stage 7; every lead lands as `New`. Run the drafter → **zero** drafts. Flip one lead to
   `Approved` by hand, re-run → exactly one draft, that lead alone moves to `Drafted`. Re-run → no re-draft. Assert no
   code path auto-advances to `Sent`.
10. **Dedup.** Re-run stage 7 immediately → zero new lead rows.
11. **Digest.** `valid`, `accept_all`, and no-email rows each render in their correct form, with the LinkedIn fallback
    visible on the third.
12. **Persona correctness.** A lead whose coregent record is `is_recruiter_like` is not labeled `hiring_manager` and is
    not used as prong 2's cold-email target.
13. **Dead-code wiring.** For a job with a matched lead, the cold-email draft contains a real hiring-manager line (not
    the bare `- ` bullet) and the job row's `Hiring Manager LinkedIn` is populated.

---

## Risks

- **Phase 0 is load-bearing.** The verification policy, the `linkedin_handle` shortcut, and the coregent field map all
  depend on live output. Coding before the spike returns means guessing at exactly the things the governing rule
  forbids guessing about.
- **Free-tier capacity is the real constraint.** ~33–50 people/month, roughly one a day. The subsystem is selective by
  construction; that is a feature for outreach, but prong 2 will never be high-volume.
- **`accept_all` may swallow your best targets.** Large product companies often run catch-all domains, so top-tier
  employers may persistently land in the "unverified" bucket. That is Hunter telling the truth, not a bug — but expect it.
- **`is_direct_job_poster` is frequently false.** Many postings expose no hiring-team member. Expect meaningful yield
  loss; that is why Mode A is cheap (person-less jobs are not billed) and why Mode B exists as a fallback.
- **Still personal data.** No-cookie removes *account* ban risk, not GDPR/CCPA obligations. Leads are people. The
  human-sends-manually gate is non-negotiable, and no lead data leaves Notion.
- **Vendor concentration.** coregent is one third-party riding LinkedIn's public guest endpoints, which LinkedIn can
  close. Verification step 1 exists so that breakage is loud rather than a silent zero.
- **Mode B cost** (~$9/mo daily) is real. Keep it off by default; run it weekly if enabled.
- **CI metering is a new, real cost.** Scheduled runs cannot use the Claude Code subscription; they bill per token
  against `ANTHROPIC_API_KEY`. Volume is small (a handful of jobs and leads per day), but it is no longer $0. Keep the
  cheap model on stage 7's persona ranking (`AI_MODEL_OVERRIDE`), reserving `QUALITY_MODEL` for drafting.
- **Two providers means two code paths that can drift.** CI exercises `claude`; you exercise `claude_code` locally.
  Verification step 6 exists specifically to catch a stage that works on one and not the other.
- **Secrets are moving into GitHub, and one is already burned.** `APIFY_API_TOKEN` (`settings.py:142`) is in git
  history and must be rotated before any workflow references it. Gmail's installed-app OAuth needs a one-time local
  consent before it can run headless.
