# Constraints

## Binding decisions

- **No authenticated LinkedIn scraping.** Anything requiring an `li_at` session cookie risks
  restricting the very account whose network this feature exists to leverage. Public,
  unauthenticated endpoints only.
- **Hunter free tier, budget-gated.** 50 credits/month; Email Finder = 1 credit per email *found*
  (0 if not found), Verifier = 0.5. Needs a budget guard and a priority queue ordered by ATS score.
  A repeated identical search is counted once per calendar month, so caching is genuinely free.
- **`accept_all` policy.** Many large product companies run catch-all domains where SMTP can't
  confirm a specific mailbox. Record the address only when Hunter itself returned it (never
  constructed from Hunter's `pattern` field) and `score ≥ ACCEPT_ALL_MIN`; persist
  `Email Status = accept_all`, `Verified = false`. Digest renders it as "unverified — send at your
  discretion." It never counts as verified.
- **Scheduling: GitHub Actions** (cron + `workflow_dispatch`), with the local agentic orchestrator
  remaining usable by hand.

## Why GitHub Actions reshapes the design

1. **The provider split stops being optional.** `AI_PROVIDER = "claude_code"` requires an
   interactive `claude /login` session, which cannot exist on a GitHub runner — CI must run
   `AI_PROVIDER="claude"` with a metered key. `settings.py`'s `AI_PROVIDER` becomes
   `os.environ.get("AI_PROVIDER", "claude_code")`: local behavior unchanged, CI overrides via env.
2. **Ephemeral runners kill a SQLite credit ledger.** `actions/cache` is evictable and would
   silently lose spend history; committing a binary DB back to the repo invites races. Replaced
   with Hunter's own free `GET /v2/account` (authoritative, real-time remaining quota) — query
   before draining the queue, stop at the reserve floor. Mutual exclusion moves to a
   `concurrency:` group; the company→domain cache moves to committed `config/company_domains.json`.
3. **Ephemeral filesystem means outputs must leave the runner.** Drafts are written into the
   Notion lead page body (durable, and where the human reviews anyway), mirroring how
   `db_add_job` already caches the JD in the job page body. Workflow artifacts are a secondary
   copy. Gmail OAuth's consent flow can't run headless — do it once locally, store the
   refresh-token JSON as a GitHub Secret, materialize it at job start (or ship CI with `--send`
   off initially).

Secret rotation: `APIFY_API_TOKEN` is a committed plaintext literal in git history — rotate it and
move it env-only before any workflow references it. Same bar for `HUNTER_API_KEY`.

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
