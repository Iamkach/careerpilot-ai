# Verification

Each acceptance-criteria.md bullet is written as a concrete, testable scenario — this section is
the index of how to actually run them, not a separate list.

**Automated (mocked, no live API keys needed for the default suite):** follow the existing
`patch_ai_chat`/`patch_notion_db` fake pattern in `tests/conftest.py`. New test files land
alongside the new stage scripts: `tests/test_stage7_leads_discover.py`,
`tests/test_stage8_email_resolve.py`, `tests/test_credits.py`. Key cases to cover (mirrors
acceptance-criteria.md): loud failure on a bad actor call; dedup on `linkedin_profile_url`; the
`accept_all` three-way policy table; `pattern` never reaching the `Email` property; the AI ranking
validator dropping any `idx` outside the input set; the approval gate (`Approved` → exactly one
draft, re-run does not re-draft, nothing auto-advances to `Sent`).

**Real-API spike (Phase 0, one-time, costs a small amount of Hunter/Apify credit):** run `coregent`
against 1-2 real Notion jobs, inspect the raw dataset, and hit Hunter's Email Finder once for each
of the four Phase-0 questions in plan.md. Record the answers directly in this feature's meta.md
or plan.md before writing any Phase 1+ code — this spike is a hard prerequisite, not advisory.

**CI parity check, once `.github/workflows/communications.yml` exists:** trigger a
`workflow_dispatch` run and confirm it succeeds under `AI_PROVIDER=claude` with no `claude /login`
session, then run the same stage locally under `claude_code` and confirm equivalent output —
this is the CI-parity acceptance criterion.

**Manual, after a real (non-mocked) run:** confirm every draft is readable in the Notion lead page
body, not only the workflow artifact; confirm the Leads DB's pre-created select options survived
(a renamed property should throw, not silently no-op).
