# Step 11 — Forkable setup (`--init` wizard + Notion provisioning + de-personalization)

**Status:** **Phase 1 (Notion) landed · Phase 2 (identity) remaining.**
**Priority:** P1 — a fork still can't run without editing `config/settings.py` (owner identity is
hardcoded), even though the Notion side is now one command.
**Depends on:** `config/settings.py` env/overlay loading (`_load_local_env`, `_apply_saved_profile`),
the `db_*` / `_notion()` layer in `scripts/utils.py`, and `run.py --init`/`--setup`.
**Size:** M total; **S remaining.**
Full design + exact line references:
[`../refinement-plans/onboarding/forkable-setup.md`](../refinement-plans/onboarding/forkable-setup.md).

## Phase 1 — landed (commits `3f81018` + `9ddeabb`)

- **`scripts/provision_notion.py`** — canonical schema (25 properties / 21 `Status` options, from
  the live DB; adds `Enrichment Attempts`). `pages.create` + three `databases.create` build the
  **"Careerpilot-ai" page + Job Search Tracker + Job Link Scratch Pad + Restricted Sponsorship
  Companies**; `normalize_page_id()`
  accepts a share link; `validate_schema()` hardens `--setup`.
- **`run.py --init`** — Notion onboarding wizard; **`NOTION_DB_ID` env-sourced** (literal removed);
  `check_setup()` validates the live schema. `setup_notion_schema.py` imports the Stage-7 subset so
  create/patch can't drift. Docs: `README`/`SETUP`/`.env.example`/`SKILL.md`/`CLAUDE.md`.

> **⚠ CI follow-up from Phase 1 (local already done):** the owner's local `.env` already carries
> `NOTION_DB_ID`, so local runs are fine. **CI is not:** `_load_local_env()` no-ops under
> `GITHUB_ACTIONS`, and the nightly workflow `env:` block sets `NOTION_API_KEY` but not
> `NOTION_DB_ID` — with the default removed, the scheduled run points at an empty id. Add a
> `NOTION_DB_ID` repo secret + `NOTION_DB_ID: ${{ secrets.NOTION_DB_ID }}` to the workflow env
> block (and the also-missing `APIFY_API_TOKEN`) **before the next scheduled run**.

## Phase 2 — remaining (identity / de-personalization)

Owner identity is still hardcoded in `config/settings.py`: `YOUR_NAME` (L26), `YOUR_EMAIL` (L27),
`YOUR_BIO` (L28), `TARGET_ROLES` (L31), `TARGET_COMPANIES` (L35), `RESUME_TEMPLATE_PATH` (L317,
`config/Achyuth_Resume.docx`), `AI_PROVIDER` (L326, `"codex"`). `config/resume.txt`,
`config/Achyuth_Resume.docx`, and `config/ats_tokens.json` are still tracked.

- **`config/profile.json`** (git-ignored) + tracked `config/profile.example.json` — identity/targets
  loaded via a `_load_profile()` overlay (same pattern as `application_profile.json`); literals
  become generic-defaulted `profile.get(...)`, `AI_PROVIDER` default → `"claude"`.
- **`--init` gains a profile section** — one wizard sets identity too (separate, skippable block).
- **De-personalize** — `git rm --cached` the resume/ats-token files (keep local), add
  `config/resume.example.txt`, extend `.gitignore`, and genericize `Achyuth`/`Iamkach`/DB-id refs
  in `.claude/agents/*`, `.claude/skills/careerpilot-ai/SKILL.md`, `README`/`SETUP`,
  `code-changes-management/README.md`, `scripts/render_docx.py`, `scripts/stage2_tailor.py`. (Leave
  historical docs + test fixtures untouched.)
- **Tests** — profile overlay (override + missing/corrupt) and the `--init` profile block, mocked.

## Security note

The local git-ignored `.env` and `config/gmail_credentials.json` contain the owner's **live** keys.
Not committed — but if the repo/history is ever published, rotate them.
