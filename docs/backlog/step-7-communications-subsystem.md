# Step 7 — Communications subsystem (Stages 7–8: LinkedIn leads + verified cold email)

**Priority:** P3 — most complex story in the roadmap; last for a reason. Only starts after its own
blocking Phase-0 spike returns.
**Depends on:** Step 6 (benefits from Conflict C6 — an earlier `valig` LinkedIn actor swap in Step
1/6 hands this story free recruiter contact data), Step 5 (Conflict C4 — `classify_company_type()`
decision)
**Size:** XL — two new stages, a new Notion database (~22 props), a new module, a digest refactor,
two new vendors, a new execution model (GitHub Actions)
**Source plan(s):**
[`refinement-plans/communications/communications-subsystem.md`](../refinement-plans/communications/communications-subsystem.md)
(full spec — this story is a condensed implementation checklist; read the source doc's Phases 0-6
before starting)

## Context

Two prongs, one subsystem: (1) find the people attached to live job reqs (poster, recruiter,
hiring manager) via LinkedIn, keep them as durable Leads, draft targeted outreach behind a manual
approval gate; (2) for top-ATS jobs, identify who's worth contacting and resolve a **verified**
professional email via Hunter.io. **Governing rule: APIs supply facts; AI ranks and writes** — the
AI never invents a name, title, email, or domain; a code-level validator enforces this, not the
prompt.

Today there is no scheduling infrastructure, no contact-data source, no Leads store, and no digest
section primitive. This is largely greenfield.

## Phase 0 — blocking spike (do this first; nothing downstream is written until it returns)

1. Does Hunter's Email Finder return a terminal `verification.status` inline, or
   `pending`/`null`? This decides whether the Verifier (0.5 credit) is ever needed — code the
   wrong policy and capacity silently drops from ~50/month to ~33.
2. Does the free tier honor Email Finder's `linkedin_handle` param? If yes, a coregent profile URL
   feeds Hunter directly and domain resolution is skipped entirely.
3. Confirm billing edges: not-found = 0 credits; what an `accept_all` hit actually costs.
4. Is Clearbit's keyless autocomplete still up? Run `coregent` against 1-2 real Notion jobs with
   `maxResults=3`, inspect raw dataset keys, write the field map against **real output**, confirm
   person-less jobs aren't billed.

## What to do (Phases 1-6, after the spike)

### Phase 1 — Foundations (zero spend)

- **`scripts/credits.py` (new)** — thin budget guard over Hunter's free `GET /v2/account` (not a
  ledger — GitHub Actions runners are ephemeral, so no SQLite). Exposes `remaining()` /
  `can_spend(n)` / `reserve_floor`; owns `config/company_domains.json` (committed cache).
- **`scripts/utils.py`** — add `db_id` param to `_query_db` (currently hardwires `NOTION_DB_ID`);
  add `_notion_create_page(db_id, props)`, `_notion_query(db_id, filter)`, `_safe_select(value,
  allowed, default)`; build `db_add_lead()` / `db_get_leads(status)` / `db_update_lead_status()`.
  **These must let exceptions propagate** — do not repeat `_notion_write_job`'s bare `except`.
- **`config/settings.py`** — `HUNTER_API_KEY` (env), `NOTION_LEADS_DB_ID`, budget constants, score
  thresholds, `LEAD_ACTOR`, `LEAD_MIN_RELEVANCE = 60`, `LEAD_DISCOVERY_MODE = False`. Confirm
  `APIFY_API_TOKEN` was already rotated in Step 0 — do not repeat that pattern for `HUNTER_API_KEY`.
- Create the Notion **Leads DB** by hand (schema below) — **pre-create every select option**
  before any writer code runs.

### Phase 2 — Prong 1: `scripts/stage7_leads_discover.py` (new)

- **Mode A (default)** — job-linked, input = `job_url`s already `Status = Reviewed`
  (~5-10 leads ≈ $0.02/run). **Mode B (opt-in, off by default)** — discovery via
  `TARGET_ROLES × TARGET_COMPANIES` (~125 leads ≈ $0.30/run, ~$9/mo daily). Mode A finally gives
  `TARGET_COMPANIES` a consumer.
- Call `_apify_run(LEAD_ACTOR, payload)` — reuse as-is, it's actor-agnostic.
- **Let it fail loudly.** Do not copy `scrape_indeed`'s `except Exception: return []` — that is the
  exact bug class this story must not repeat. A failed run exits non-zero; an empty-but-successful
  run exits 0 with "0 leads" logged.
- Filter recruiters at staffing firms via `is_skipped_company()` (pure name check, no AI needed —
  the actor's own `is_recruiter_like`/`is_direct_job_poster`/`relevance_score` already do
  persona classification, so skip re-implementing a regex+LLM pass).
- Drop below `LEAD_MIN_RELEVANCE` (60).
- Dedup on `linkedin_profile_url` against a single `db_get_leads()` snapshot (same in-memory
  pattern as Stage 1's URL set). Upsert keyed on that URL.
- Reuse `_open_drop_log`/`_log_drop` with reasons `company`, `low-relevance`, `duplicate`,
  `no-profile-url`.
- **Conflict C4:** if `company_type` AI classification is wanted here, it depends on Step 5's
  decision to extract `classify_company_type()` standalone. If Step 5 chose not to, use
  `is_skipped_company()` alone — do not re-implement the classifier here.

### Phase 3 — Prong 2: `scripts/stage8_email_resolve.py` (new)

- Priority queue over top-ATS jobs, drained until budget exhausted; remainder stays `Ranked` and
  the process exits 0.
- **Domain resolution chain, cheapest first**, every result cached in `company_domains.json`:
  1. `linkedin_handle` on Email Finder (no domain resolution needed at all — preferred).
  2. `company_domains.json` cache hit.
  3. The job's own apply/ATS URL already in Notion.
  4. Clearbit keyless autocomplete (any failure = "unresolved," never a blocker).
  5. **Never** use Hunter Domain Search merely to get a domain (bills per email returned) — it's a
     person-discovery tool for prong 2's hiring-manager search, not a domain resolver.
- If 1-4 all fail: no domain → no Email Finder call → LinkedIn fallback + "no verified email" flag.
  **Never guess a domain.**
- Email policy (final shape depends on Phase-0 spike answer #1):

  | Hunter result | Action |
  |---|---|
  | `valid`, `score ≥ VALID_MIN` | Record, `Verified = true` |
  | `accept_all`, address present, `score ≥ ACCEPT_ALL_MIN` | Record, `Verified = false`, `Email Status = accept_all`, digest shows "unverified — send at your discretion" |
  | `invalid` / `webmail` / `disposable` | No email; LinkedIn fallback + flag |
  | `unknown`/`pending`/`null` | One Verifier call (0.5 cr), re-apply this table |

- **Hunter's `pattern` field is display-only and must have zero code path into the `Email`
  property** — this is the literal encoding of "never pattern-match." Give it its own unit test.

### Phase 4 — AI ranking + drafting + the approval gate

- Rank contacts: `ai_chat(..., quality=True)` + `parse_json_response()`. In:
  `{"job": {...}, "candidates": [{"idx","name","title","seniority","department","linkedin"}]}`.
  Out: `{"ranked": [{"idx","persona","worth_contacting","priority","reason"}]}`.
  **The guardrail is code, not the prompt**: after parsing, validate every returned `idx` against
  the input set and drop anything referencing a name/email not present in it.
- Draft: add `draft_connection_request(lead)` modeled on the existing
  `draft_warm_referral()`. Wire the two currently-dead paths this finally activates:
  `_draft_cold_email_single`'s `hm_name`/`hm_context` params (currently always empty, so the
  hiring-manager line renders as a bare `- ` bullet), and `_EXTRA_TO_NOTION`'s
  `hiring_manager`/`hiring_manager_linkedin` mappings (defined, never written).
  `stage5_interview_prep.py:150` already reads `job["hm_li"]` and lights up for free once this
  lands.
- Fix `save_draft()` (`stage3_outreach.py:140`): add `encoding="utf-8"` — a latent Windows cp1252
  crash on real human names.
- **The gate:** leads reach `Drafted` only after a human sets `Approved` in Notion. Nothing
  auto-advances to `Sent`. No automated connecting or messaging, ever.

### Phase 5 — Digest (`scripts/stage4_digest.py`)

- Hoist shared CSS into a plain module constant `_DIGEST_STYLE` (removes `{{ }}` f-string
  doubling).
- Add `render_html_section(title, headers, rows, notice="")`, `render_plain_section(...)`,
  `build_html_page(sections)`.
- Re-express the existing two digests as sections (behavior-preserving), then add **LinkedIn
  Leads** and **Cold Email Contacts** sections. The latter renders `valid` normally, `accept_all`
  with the unverified note, no-email rows as a LinkedIn URL + visible flag.

### Phase 6 — Wiring, scheduling, manual runs

- `workflow.py`: add `run_leads_discover` / `run_email_resolve` to **both** `_TOOL_IMPL` and
  `TOOLS` (a missing entry in either is a `KeyError` at import). Add read-only `get_leads`
  (bypasses `_STAGE_LOCK`, like `get_jobs`). Add `_TASK_BUILDERS` entries so `--task leads` /
  `--task emails` work locally under the subscription.
- **New `.github/workflows/communications.yml`** — cron + `workflow_dispatch`, `concurrency:
  {group: communications, cancel-in-progress: false}` (replaces the SQLite lock), three
  **sequential** jobs: `discover_leads` (`python run.py --stage 7`) → `resolve_emails` (budget-gated
  via `/v2/account`, exits 0 when quota spent) → `digest` (uploads `output/` as artifact).
  Sequential deliberately — Hunter's ~1-person/day budget means parallelism buys nothing.
- Every CI job sets `AI_PROVIDER=claude`, pulls `ANTHROPIC_API_KEY`/`NOTION_API_KEY`/
  `HUNTER_API_KEY`/`APIFY_API_TOKEN` from GitHub Secrets.
- `settings.py:125` becomes `AI_PROVIDER = os.environ.get("AI_PROVIDER", "claude_code")` — local
  behavior unchanged, CI overrides via env.
- Drafts write to the **Notion lead page body** (durable) — the runner's filesystem is ephemeral,
  so `output/` is a secondary artifact copy only.
- Gmail OAuth: do the consent flow once locally, store the refresh-token JSON as a GitHub Secret,
  materialize it to `GMAIL_CREDENTIALS_PATH` at job start. If fiddly, ship CI with `--send` off
  initially and read the digest from the artifact.

## Notion Leads DB schema (create before any writer code)

`Name` (title) · `Lead Title` · `Company` · `Team` · `LinkedIn URL` (url) · `Linked Job`
(relation → Jobs DB) · `Job Title` · `Job URL` (url) · `Prong` (select: `linkedin`, `cold_email`) ·
`Source` (select: `coregent`, `hunter_domain_search`, `manual`) · `Persona` (select:
`hiring_manager`, `team_lead`, `peer`, `referrer`, `recruiter`) · `Is Direct Job Poster`
(checkbox) · `Is Recruiter-like` (checkbox) · `Relevance Score` (number) · `Reason Tags`
(multi_select) · `Email` (email) · `Email Status` (select: `valid`, `accept_all`, `none`) ·
`Email Score` (number) · `Verified` (checkbox) · `No Verified Email` (checkbox) · `Email Note` ·
`Outreach Status` (select: `New → Ranked → Approved → Drafted → Sent → Replied → Connected` +
`Skipped`) · `Draft Link` · `Last Hunter Attempt` (date)

## Acceptance criteria

- [ ] Phase-0 spike answers recorded before any Phase 1+ code is written.
- [ ] Loud failure: point `LEAD_ACTOR` at garbage → non-zero exit, nothing written. Empty-but-real
      run → exit 0, "0 leads." Same for a Hunter 401/429.
- [ ] Leads DB created by hand first; renaming one property afterward produces a real, logged
      Notion exception — not a silent no-op.
- [ ] `accept_all` policy: (a) score ≥ threshold + address present → persisted, unverified note in
      digest; (b) score < threshold → no email; (c) only `pattern` present, no address → Email
      property stays empty.
- [ ] Unit test proves `pattern` has zero code path to the `Email` property, and the AI validator
      drops any returned idx/name/email absent from the API input set.
- [ ] Credit budget: cap reserve floor to 2 spendable credits, enqueue 5 jobs → ≤2 spent, 3 remain
      `Ranked`; re-querying the same search in the same calendar month costs Hunter **0**.
- [ ] CI parity: `workflow_dispatch` run with `AI_PROVIDER=claude` succeeds with no `claude /login`
      session; local run under `claude_code` produces equivalent output; `ANTHROPIC_API_KEY`
      confirmed absent from the local environment.
- [ ] After a CI run, every draft is readable in the Notion lead page body, not only the artifact.
- [ ] A staffing-firm recruiter is dropped `company`; a relevance score of 40 is dropped
      `low-relevance`.
- [ ] The gate holds: stage 7 lands every lead as `New`; running the drafter with none `Approved`
      produces zero drafts; approving one by hand produces exactly one draft, moving only that lead
      to `Drafted`; re-running does not re-draft it; no code path auto-advances to `Sent`.
- [ ] Re-running stage 7 immediately produces zero new lead rows (dedup holds).
- [ ] Digest renders `valid`, `accept_all`, and no-email rows in their distinct correct forms.
- [ ] A lead whose coregent record is `is_recruiter_like` is never labeled `hiring_manager` and is
      never used as prong 2's target.
- [ ] For a job with a matched lead, the cold-email draft contains a real hiring-manager line (not
      a bare `- ` bullet) and the job row's `Hiring Manager LinkedIn` is populated.

## Out of scope

- Any automated sending/connecting — the human-approval gate is non-negotiable per the governing
  rule; do not build a "Sent" auto-transition even as a future toggle.
- Scaling Mode B beyond weekly cadence — real cost (~$9/mo), keep opt-in.

## Files touched

`scripts/credits.py` (new), `scripts/stage7_leads_discover.py` (new),
`scripts/stage8_email_resolve.py` (new), `scripts/utils.py`, `scripts/stage3_outreach.py`,
`scripts/stage4_digest.py`, `config/settings.py`, `config/company_domains.json` (new),
`workflow.py`, `.github/workflows/communications.yml` (new), `CLAUDE.md`.

## References

- Architecture analysis §C.6 (Stages 7-8 flow diagram), §C.9 (complexity ranking — Plan 5 ranks
  most complex).
- `refinement-plans/README.md` Step 7.
- `refinement-plans/communications/communications-subsystem.md` — full spec; its "Verification"
  section (items 1-13) and "Risks" section map directly onto the acceptance criteria and
  out-of-scope notes above.
