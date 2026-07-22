# Step 11 — Forkable setup (one-time `--init` wizard + Notion auto-provisioning)

**Status:** Notion-provisioning half **landed** — `scripts/provision_notion.py` (creates the
"Careerpilot-ai" page + Job Search Tracker + Job Link Scratch Pad databases with the full schema),
`python run.py --init` wizard, env-sourced `NOTION_DB_ID` (hardcoded literal removed), and a
schema-validating `python run.py --setup`. **Still deferred:** `config/profile.json` for
identity/targets, untracking the personal resume files + `ats_tokens.json`, and genericizing owner
references across docs/`.claude/*`. (Full spec at
[`../refinement-plans/onboarding/forkable-setup.md`](../refinement-plans/onboarding/forkable-setup.md).)
**Priority:** P1 — the repo cannot be forked and run by anyone else today without editing code and
hand-building a Notion database.
**Depends on:** existing `config/settings.py` env-loading (`_load_local_env`), the `db_*` /
`_notion()` layer in `scripts/utils.py`, and `run.py --setup`.
**Size:** M.

## Problem

A fork does not run out of the box. Identity is hardcoded in `config/settings.py`
(`YOUR_NAME`/`YOUR_EMAIL`/`YOUR_BIO`, `TARGET_ROLES`, `TARGET_COMPANIES`, `RESUME_TEMPLATE_PATH`,
`AI_PROVIDER`), and `NOTION_DB_ID` (L256) is a literal pointing at the **author's own private
database** — the only non-env-sourced secret, and one `--setup` only null-checks. Nothing in the
repo creates the Notion tracker DB (18 properties + 14 `Status` options are manual today), and the
owner's real `config/resume.txt` / `config/Achyuth_Resume.docx` are committed.

## What ships

- **`config/profile.json`** (git-ignored) + tracked `config/profile.example.json` — identity/targets
  loaded by `settings.py`; hardcoded literals replaced with generic-defaulted `profile.get(...)`.
- **`NOTION_DB_ID` becomes env-sourced** (`os.environ.get`), added to `.env.example` and the CI env
  block (alongside the currently-missing `APIFY_API_TOKEN`).
- **`scripts/provision_notion.py`** — one `databases.create` call builds the full tracker schema
  (all 14 `Status` options defined up front, sidestepping the API's "can't add options on write"
  limit) under a page the forker shares with their integration; returns the new DB id. Also exposes
  `validate_schema()` used to harden `check_setup()`.
- **`python run.py --init`** — interactive wizard: writes `.env` + `config/profile.json`, provisions
  the DB, persists the new id. Every value stays hand-settable (file fallback) for CI/power users.
- **De-personalize**: untrack the resume files + `ats_tokens.json` (keep local), add a
  `resume.example.txt` placeholder, and genericize owner references across docs and `.claude/*`.

Full design, exact line references, and the verification plan are in the refinement plan linked above.

## Security note

The local git-ignored `.env` and `config/gmail_credentials.json` contain the owner's **live** keys.
They are not committed, but if the repo/history is ever published they should be rotated.
