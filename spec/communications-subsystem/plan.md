# Plan

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

## Phase 1 — Foundations (zero spend)

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
- Create the Notion **Leads DB** by hand (schema in constraints.md) — **pre-create every select
  option** before any writer code runs.

## Phase 2 — Prong 1: `scripts/stage7_leads_discover.py` (new)

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
- **Cross-story dependency:** if `company_type` AI classification is wanted here, it depends on
  Step 5's decision to extract `classify_company_type()` standalone. If Step 5 chose not to, use
  `is_skipped_company()` alone — do not re-implement the classifier here.

## Phase 3 — Prong 2: `scripts/stage8_email_resolve.py` (new)

- Priority queue over top-ATS jobs, drained until budget exhausted; remainder stays `Ranked` and
  the process exits 0.
- **Domain resolution chain, cheapest first**, every result cached in `company_domains.json`:
  1. `linkedin_handle` on Email Finder (no domain resolution needed at all — preferred).
  2. `company_domains.json` cache hit.
  3. The job's own apply/ATS URL already in Notion.
  4. Clearbit keyless autocomplete (any failure = "unresolved," never a blocker).
  5. **Never** use Hunter Domain Search merely to get a domain (bills per email returned).
- If 1-4 all fail: no domain → no Email Finder call → LinkedIn fallback + "no verified email" flag.
- Email policy (final shape depends on Phase-0 spike answer #1):

  | Hunter result | Action |
  |---|---|
  | `valid`, `score ≥ VALID_MIN` | Record, `Verified = true` |
  | `accept_all`, address present, `score ≥ ACCEPT_ALL_MIN` | Record, `Verified = false`, `Email Status = accept_all`, digest shows "unverified — send at your discretion" |
  | `invalid` / `webmail` / `disposable` | No email; LinkedIn fallback + flag |
  | `unknown`/`pending`/`null` | One Verifier call (0.5 cr), re-apply this table |

- **Hunter's `pattern` field is display-only and must have zero code path into the `Email`
  property** — give it its own unit test.

## Phase 4 — AI ranking + drafting + the approval gate

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

## Phase 5 — Digest (`scripts/stage4_digest.py`)

- Hoist shared CSS into a plain module constant `_DIGEST_STYLE` (removes `{{ }}` f-string
  doubling).
- Add `render_html_section(title, headers, rows, notice="")`, `render_plain_section(...)`,
  `build_html_page(sections)`.
- Re-express the existing two digests as sections (behavior-preserving), then add **LinkedIn
  Leads** and **Cold Email Contacts** sections. The latter renders `valid` normally, `accept_all`
  with the unverified note, no-email rows as a LinkedIn URL + visible flag.

## Phase 6 — Wiring, scheduling, manual runs

- Add `run_leads_discover` / `run_email_resolve` stage entry points, wired the same way every
  other `run.py --stage N` entry is (the original doc referenced a `workflow.py` tool-registry
  pattern that has since been removed from this codebase — see CLAUDE.md's "Single entry point"
  section; wire through `run.py`'s existing `--stage` dispatch instead).
- **New `.github/workflows/communications.yml`** — cron + `workflow_dispatch`, `concurrency:
  {group: communications, cancel-in-progress: false}` (replaces the SQLite lock), three
  **sequential** jobs: `discover_leads` (`python run.py --stage 7`) → `resolve_emails` (budget-gated
  via `/v2/account`, exits 0 when quota spent) → `digest` (uploads `output/` as artifact).
  Sequential deliberately — Hunter's ~1-person/day budget means parallelism buys nothing.
- Every CI job sets `AI_PROVIDER=claude`, pulls `ANTHROPIC_API_KEY`/`NOTION_API_KEY`/
  `HUNTER_API_KEY`/`APIFY_API_TOKEN` from GitHub Secrets.
- `settings.py`'s `AI_PROVIDER` becomes `os.environ.get("AI_PROVIDER", "claude_code")` — local
  behavior unchanged, CI overrides via env.
- Drafts write to the **Notion lead page body** (durable) — the runner's filesystem is ephemeral,
  so `output/` is a secondary artifact copy only.
- Gmail OAuth: do the consent flow once locally, store the refresh-token JSON as a GitHub Secret,
  materialize it to `GMAIL_CREDENTIALS_PATH` at job start. If fiddly, ship CI with `--send` off
  initially and read the digest from the artifact.

## Files touched

`scripts/credits.py` (new), `scripts/stage7_leads_discover.py` (new),
`scripts/stage8_email_resolve.py` (new), `scripts/utils.py`, `scripts/stage3_outreach.py`,
`scripts/stage4_digest.py`, `config/settings.py`, `config/company_domains.json` (new),
`run.py` (stage wiring — see Phase 6 note on `workflow.py` being retired),
`.github/workflows/communications.yml` (new), `CLAUDE.md`.

## Risks

- **Phase 0 is load-bearing** — the verification policy, the `linkedin_handle` shortcut, and the
  coregent field map all depend on live output; coding before the spike returns means guessing at
  exactly what the governing rule forbids guessing about.
- **Free-tier capacity is the real constraint** — ~33-50 people/month, roughly one a day. Selective
  by construction; a feature for outreach, but prong 2 will never be high-volume.
- **`accept_all` may swallow the best targets** — large product companies often run catch-all
  domains, so top-tier employers may persistently land "unverified." That's Hunter telling the
  truth, not a bug.
- **`is_direct_job_poster` is frequently false** — many postings expose no hiring-team member;
  expect meaningful yield loss (Mode A stays cheap since person-less jobs aren't billed; Mode B is
  the fallback).
- **Still personal data** — no-cookie removes account ban risk, not GDPR/CCPA obligations. The
  human-sends-manually gate is non-negotiable; no lead data leaves Notion.
- **Vendor concentration** — coregent rides LinkedIn's public guest endpoints, which LinkedIn can
  close; acceptance criterion "loud failure" exists so that breakage is loud, not a silent zero.
- **Mode B cost** (~$9/mo daily) is real — keep off by default, run weekly if enabled.
- **CI metering is a new, real cost** — scheduled runs bill per token against `ANTHROPIC_API_KEY`
  instead of riding the subscription. Volume is small but no longer $0; keep the cheap model on
  stage 7's persona ranking, reserve `QUALITY_MODEL` for drafting.
- **Two providers, two code paths that can drift** — CI exercises `claude`, local exercises
  `claude_code`; the CI-parity acceptance criterion exists to catch a stage that works on one and
  not the other.

## References

- `docs/architecture/architecture-analysis.md` §C.6 (Stages 7-8 flow diagram), §C.9 (complexity
  ranking — this plan ranks most complex).
