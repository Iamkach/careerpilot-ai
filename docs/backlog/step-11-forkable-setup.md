# Step 11 — Forkable setup (`--init` wizard + Notion provisioning + de-personalization)

**Status:** **Phase 1 (Notion) landed · Phase 2 (identity) remaining.**
**Priority:** P1 — a fork still can't run without editing `config/settings.py` (owner identity is
hardcoded), even though the Notion side is now one command.
**Depends on:** `config/settings.py` env/overlay loading (`_load_local_env`, `_apply_saved_profile`),
the `db_*` / `_notion()` layer in `scripts/utils.py`, and `run.py --init`/`--setup`.
**Size:** M total; **S remaining.**

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

**Goal:** no owner identity in tracked source. A forker's name/targets/resume live in git-ignored
config; the checked-in tree carries only generic placeholders. `--init` grows a profile section so
the same one command sets identity too.

Owner identity is still hardcoded in `config/settings.py` (verified line numbers): `YOUR_NAME`
(L26, `"Krishna Achyuth"`), `YOUR_EMAIL` (L27, `"kachyuth06@gmail.com"`), `YOUR_BIO` (L28, owner's
paragraph), `TARGET_ROLES` (L31, owner's five roles), `TARGET_COMPANIES` (L35, owner's five
companies), `RESUME_PATH` (L312, `"config/resume.txt"`), `RESUME_TEMPLATE_PATH` (L317,
`config/Achyuth_Resume.docx`), `AI_PROVIDER` (L326, `"codex"` — not the documented `"claude"`
default). Tracked personal artifacts (via `git ls-files config/`): `config/resume.txt`,
`config/Achyuth_Resume.docx`, `config/ats_tokens.json`.

### 2a. Profile config (`config/settings.py` + new files)

- **New `config/profile.example.json`** (tracked, generic placeholders):
  ```json
  {
    "name": "Your Name",
    "email": "you@example.com",
    "bio": "One-paragraph professional summary used in outreach drafts.",
    "target_roles": ["Software Engineer", "Senior Software Engineer"],
    "target_companies": ["Stripe", "Notion", "Figma"],
    "resume_path": "config/resume.txt",
    "resume_template_path": "config/resume.docx",
    "ai_provider": "claude"
  }
  ```
- **`config/settings.py`:** add a `_load_profile()` helper mirroring `_load_local_env()` (top of
  file) that reads a git-ignored `config/profile.json` if present (missing/corrupt → `{}`, defaults
  stand — same contract as `_apply_saved_profile()` already uses for `application_profile.json`).
  Replace each literal above with `_profile.get(<key>, <generic default>)`. Defaults: drop the
  owner name/email/bio to the `profile.example.json` placeholders; `RESUME_TEMPLATE_PATH` →
  `"config/resume.docx"` (no owner filename); `AI_PROVIDER` → `"claude"`.
  - Keep `SKIP_COMPANIES`, `SKIP_COMPANY_KEYWORDS`, `RESTRICTED_SPONSORSHIP_COMPANIES`, and the
    tuning constants as-is — generic reusable defaults, not identity.
  - **Reuse, don't reinvent:** the `application_profile.json` overlay (`_apply_saved_profile()`)
    is the exact pattern to follow for `profile.json`; consider one shared JSON-overlay helper.

### 2b. Extend `--init` with a profile section

- After the Notion steps in `init_wizard()` (`run.py`), prompt (pre-filled from the current
  effective value, Enter keeps it) for name / email / bio / target roles / target companies /
  resume paths / AI provider, and write `config/profile.json` (seed from `profile.example.json`
  if missing). Keep it a **separate, skippable** block so `--init` stays usable for the Notion-only
  path already shipped.
- Non-interactive fallback stays: hand-edit `config/profile.json` (+ `.env`) and skip the wizard.

### 2c. Un-track personal files

- `git rm --cached` (keep local): `config/resume.txt`, `config/Achyuth_Resume.docx`,
  `config/ats_tokens.json`.
- Add tracked placeholder `config/resume.example.txt`.
- `.gitignore`: add `config/profile.json`, `config/resume.txt`, `config/Achyuth_Resume.docx` (and
  any `config/*.docx` resume), `config/ats_tokens.json`. (`config/application_profile.json`,
  `config/gmail_credentials.json`, `config/resume_template.docx` are already ignored.)

### 2d. Genericize owner references in tracked source

Point these at `RESUME_TEMPLATE_PATH` / `NOTION_DB_ID` / profile values instead of literals
(`Achyuth`, `Iamkach`, DB id `2ac0907e...`). Confirmed occurrences worth changing:

- `.claude/agents/notion-tracker.md`, `.claude/agents/pipeline-orchestrator.md`,
  `.claude/agents/resume-tailor.md`
- `.claude/skills/careerpilot-ai/SKILL.md` (Prerequisites still names `config/Achyuth_Resume.docx`)
- `README.md`, `SETUP.md`, `code-changes-management/README.md`
- `scripts/render_docx.py`, `scripts/stage2_tailor.py` comments, `config/settings.py` comments

**Leave alone** (historical / fixtures, changing them rewrites the past for no gain):
`docs/architecture/architecture-analysis.md`, `code-changes-management/pr-11-review.md`,
`tests/conftest.py`, `tests/fixtures/**`, `tests/record_ai_responses.py`, and the recorded-response
JSON — these are point-in-time artifacts, not live config.

### 2e. Tests (mandatory — mocked)

- `config/settings.py` profile overlay: a `config/profile.json` overrides the generic defaults; a
  missing/corrupt file leaves defaults intact (mirror the existing `application_profile` tests).
- `--init` profile section: mocked `input()` writes the expected `config/profile.json` and leaves
  unrelated `.env` lines intact (extend `tests/test_provision_notion.py`'s wizard test).

## Files

- **New:** `config/profile.example.json`, `config/resume.example.txt`
- **Modify:** `config/settings.py` (profile overlay + genericized defaults), `run.py` (`--init`
  profile block), `.gitignore`, `.github/workflows/nightly-pipeline.yml` (Phase-1 follow-up),
  the doc/`.claude/*` owner references in 2d, and the Step 11 tests
- **Untrack (git rm --cached, keep local):** `config/resume.txt`, `config/Achyuth_Resume.docx`,
  `config/ats_tokens.json`

## Verification

1. **CI follow-up first:** add the `NOTION_DB_ID` secret + workflow env line; confirm a manual
   `workflow_dispatch` run reads the tracker (no empty-id abort).
2. **Fresh-fork sim:** in a scratch copy, delete `.env` + `config/profile.json`, move the resume
   files aside. `python run.py --init` end-to-end → writes `.env` (fresh `NOTION_DB_ID`) **and**
   `config/profile.json`, provisions a DB with all 25 properties / 21 Status options, and the
   effective `YOUR_NAME`/`TARGET_ROLES`/`AI_PROVIDER` reflect the answers, not the owner.
3. `python run.py --setup` → all ✓, schema validator passes; break one Notion property and confirm
   `--setup` reports it missing.
4. `git ls-files config/` shows no personal resume, resume `.docx`, or `ats_tokens.json`; `git grep`
   for `Achyuth` / `Iamkach` / `2ac0907e...` returns only the historical/fixture hits listed in 2d.
5. `pytest -v` green (mocked).

## Security note

The local git-ignored `.env` and `config/gmail_credentials.json` hold the owner's **live** keys
(Notion, Apify, OpenAI, Claude Code OAuth, Hunter, Gmail client_secret). Not committed — but if the
repo or its history is ever published, rotate them.
