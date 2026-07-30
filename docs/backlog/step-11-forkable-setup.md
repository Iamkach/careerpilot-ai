# Step 11 — Forkable setup (`--init` wizard + Notion provisioning + de-personalization)

**Status:** **Phase 1 (Notion) landed · Phase 2 (identity) landed** (2026-07-22 — profile overlay,
`--init` profile wizard + `gh` secret sync, personal files untracked, owner refs genericized,
nightly workflow wired). Verification checklist below still worth a fresh-fork dry run before close-out.
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
> block (and the also-missing `APIFY_API_TOKEN`) **before the next scheduled run**. Folded into
> the workflow changes in **2h** below (which the `--init` secret-sync in **2g** now automates).

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

- `git rm --cached` (keep local): `config/ats_tokens.json` only.
- **Resume files stay tracked as usual** — `config/resume.txt` / `config/resume.docx` (renamed
  from `config/Achyuth_Resume.docx`) remain committed to the repo, same as before Step 11.
  Rationale (reverted from an earlier draft that untracked + base64-secret-transported them):
  this repo isn't distributed as a public template a stranger forks blind — genericizing the
  *filename* (`resume.docx` instead of an owner-specific name) already gets the de-personalization
  benefit; untracking the file on top of that only adds CI-secret-transport complexity (2f/2g/2h
  in the earlier draft) for no real gain. Keep your own resume content up to date in those tracked
  files and commit it like any other file.
- Add a tracked placeholder `config/resume.example.txt` for anyone who *does* want to genuinely
  fork this and start from scratch — doesn't change that the owner's own copy stays tracked.
- `.gitignore`: add `config/profile.json` only (identity, not resume). (`config/application_profile.json`,
  `config/gmail_credentials.json`, `config/resume_template.docx`, `config/ats_tokens.json` are
  already ignored.)

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

### 2f. Resume files for CI (reverted — no base64/secret transport)

**Superseded.** An earlier draft of this plan untracked `config/resume.txt` / `config/resume.docx`
(2c) and transported them to CI as `RESUME_TXT` / base64-encoded `RESUME_DOCX_BASE64` secrets.
Reverted: resume files stay **tracked in git as usual** (2c above), so a CI checkout already has
them — no secret, no materialize step, no "resume-less run produces garbage scores" failure mode
to guard against. Keep your resume content current in those tracked files and commit it like any
other change; `run.py --setup`'s existing "Resume not found" check still fires if the tracked file
is ever missing.

### 2g. `--init` auto-pushes secrets via `gh` (with a print-only fallback)

The wizard already writes `.env` (`_upsert_env()`, `run.py`) and will write `config/profile.json`
(2b). Add a final **skippable** CI-sync block to `init_wizard()` that gets that same value into
GitHub Actions with no manual paste.

- New helper `_sync_ci_secrets()` in `run.py`. **Shell out to `gh`** (no new pip dependency —
  `subprocess` is already imported in `run.py`; the GitHub REST API path is rejected because it
  would require adding **PyNaCl** to encrypt secrets).
  - Probe `gh --version` + `gh auth status`. If both pass, push each secret:
    ```
    gh secret set PROFILE_JSON  < config/profile.json
    gh secret set NOTION_DB_ID  --body "<id>"        # + APIFY_API_TOKEN, NOTION_API_KEY, provider key
    ```
  - **Fallback (don't fail):** if `gh` is missing/unauthenticated, print the exact
    `gh secret set …` commands + a one-line "install `gh`, `gh auth login`" pointer for the user
    to run by hand. Same values, one manual step; keeps `--init` working with or without `gh`.
- Sync only the CI-relevant, non-empty set: `NOTION_API_KEY`, `NOTION_DB_ID`, `APIFY_API_TOKEN`,
  the active provider key (`ANTHROPIC_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN`), `PROFILE_JSON`. Resume
  files are **not** part of this set (2f) — skip any whose local value is empty.

### 2h. Nightly workflow consumes the secrets

- `.github/workflows/nightly-pipeline.yml` `env:` block: add
  `NOTION_DB_ID: ${{ secrets.NOTION_DB_ID }}` and `APIFY_API_TOKEN: ${{ secrets.APIFY_API_TOKEN }}`
  (this closes the Phase-1 CI follow-up above).
- Add a "materialize git-ignored config" step **after checkout, before `python run.py --setup`**
  that reconstructs `config/profile.json` from its secret (resume files need no such step — they're
  already in the checkout, per 2f):
  ```yaml
  - name: Write profile.json from secrets
    env:
      PROFILE_JSON: ${{ secrets.PROFILE_JSON }}
    run: |
      [ -n "$PROFILE_JSON" ] && printf '%s' "$PROFILE_JSON" > config/profile.json
      true
  ```
  Pass the secret through the step `env:` (indirection), **not** inline `${{ }}` in `run:`, so its
  contents never land in the shell's argv or the Actions log.
- `profile.json` absent → `_load_profile()` defaults stand (fork-friendly).

### 2e. Tests (mandatory — mocked)

- `config/settings.py` profile overlay: a `config/profile.json` overrides the generic defaults; a
  missing/corrupt file leaves defaults intact (mirror the existing `application_profile` tests).
- `--init` profile section: mocked `input()` writes the expected `config/profile.json` and leaves
  unrelated `.env` lines intact (extend `tests/test_provision_notion.py`'s wizard test).
- `--init` CI-sync (`_sync_ci_secrets()`): mocked `subprocess` — `gh` present → asserts the
  expected `gh secret set` calls (no resume-related secret among them, per the 2f revert); `gh`
  absent/unauthed → asserts it prints the fallback commands and does not raise.

## Files

- **New:** `config/profile.example.json`, `config/resume.example.txt`
- **Modify:** `config/settings.py` (profile overlay + genericized defaults), `run.py` (`--init`
  profile block **+ `_sync_ci_secrets()` gh push**), `.gitignore`,
  `.github/workflows/nightly-pipeline.yml` (Phase-1 env follow-up **+ materialize-profile-secret
  step**), the doc/`.claude/*` owner references in 2d, and the Step 11 tests
- **Untrack (git rm --cached, keep local):** `config/ats_tokens.json` only — `config/resume.txt` /
  `config/resume.docx` (renamed from `config/Achyuth_Resume.docx`) stay tracked (2c/2f).
- **New GitHub secrets** (pushed by `--init`, or by hand): `NOTION_DB_ID`, `APIFY_API_TOKEN`,
  `PROFILE_JSON` (alongside the existing `NOTION_API_KEY` / provider keys) — no resume secret.

## Verification

1. **Fresh-fork sim:** in a scratch copy, delete `.env` + `config/profile.json` (leave the tracked
   resume files in place). `python run.py --init` end-to-end → writes `.env` (fresh `NOTION_DB_ID`)
   **and** `config/profile.json`, provisions a DB with all 25 properties / 21 Status options, and
   the effective `YOUR_NAME`/`TARGET_ROLES`/`AI_PROVIDER` reflect the answers, not the owner.
2. **`--init` CI-sync (2g):** with `gh` authed, secrets appear in `gh secret list` (`PROFILE_JSON`,
   `NOTION_DB_ID`, etc. — no `RESUME_TXT`/`RESUME_DOCX_BASE64`); with `gh` uninstalled/unauthed, it
   prints the paste-ready commands and does **not** error.
3. **Nightly workflow (2h):** a manual `workflow_dispatch` run's materialize step writes
   `config/profile.json` (resume files come from the checkout itself), `run.py --setup` passes,
   and the run reads the tracker (no empty-id abort). Confirm no secret value appears in the log.
4. `python run.py --setup` → all ✓, schema validator passes; break one Notion property and confirm
   `--setup` reports it missing; with the tracked resume file deleted, `--setup` fails loud
   ("Resume not found").
5. `git ls-files config/` shows the tracked `config/resume.txt` / `config/resume.docx` but no
   `ats_tokens.json`; `git grep` for `Achyuth` / `Iamkach` / `2ac0907e...` returns only the
   historical/fixture hits listed in 2d.
6. `pytest -v` green (mocked — incl. the `_sync_ci_secrets()` gh test with mocked `subprocess`).

## Security note

The local git-ignored `.env` and `config/gmail_credentials.json` hold the owner's **live** keys
(Notion, Apify, OpenAI, Claude Code OAuth, Hunter, Gmail client_secret). Not committed — but if the
repo or its history is ever published, rotate them.
