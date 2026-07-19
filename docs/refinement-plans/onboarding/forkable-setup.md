# Forkable setup — one-time `--init` wizard + Notion auto-provisioning

*See [`../README.md`](../README.md) for how this plan relates to the others. Baseline: `feature/god-speed`.*

## Context

The repo is hardwired to the original owner, so a fork does not run without reverse-engineering
several manual steps — and one value silently points at the author's private data.

Two personalization surfaces exist today. **Secrets** are already env-sourced (`.env` locally,
repo secrets in CI) and need no rework. **Identity/profile and the Notion database** are not:

- **Identity is hardcoded** in `config/settings.py`: `YOUR_NAME` (L26), `YOUR_EMAIL` (L27),
  `YOUR_BIO` (L28), `TARGET_ROLES` (L31), `TARGET_COMPANIES` (L35),
  `RESUME_TEMPLATE_PATH` (L190, literally `config/Achyuth_Resume.docx`), and
  `AI_PROVIDER = "codex"` (L199 — the owner's choice, not the documented `"claude"` default).
- **`NOTION_DB_ID` (L256) is a hardcoded literal** pointing at the author's own Notion
  database — the *only* non-env-sourced secret. `run.py --setup`'s check (L97) only confirms the
  string is non-empty, so a forker passes setup while pointing at a DB they cannot access.
- **No code creates the Notion database.** A repo-wide search for `databases.create` finds
  nothing. All `db_*` helpers in `scripts/utils.py` read/write an *existing* DB. The 18 properties
  and the 14 `Status` select options must be built entirely by hand today.
- **Personal artifacts are committed**: `config/resume.txt` and `config/Achyuth_Resume.docx` are
  tracked and hold the owner's real resume. `config/ats_tokens.json` is an owner-seeded cache.
- Owner name / `Iamkach` GitHub handle / the hardcoded DB id are baked into `README.md`,
  `SETUP.md`, `.claude/agents/*`, and `code-changes-management/README.md`.

**Goal:** a forker runs one command — `python run.py --init` — that collects their keys and
profile, provisions their own Notion tracker DB via the API, and writes everything to git-ignored
config. Every value stays independently settable via `.env` / `config/profile.json` so power users
and CI keep a non-interactive path (file fallback). After init, `python run.py` just works.

---

## Design overview

Three layers, each usable on its own:

1. **`config/profile.json`** (git-ignored) — identity + targets, loaded by `settings.py`.
   Tracked template `config/profile.example.json`. Secrets stay in `.env` (unchanged).
2. **`scripts/provision_notion.py`** — creates the tracker DB with the full schema (all
   properties + all 14 `Status` options defined up front) under a parent page the forker shares
   with their integration; returns the new DB id. Also exposes a schema validator.
3. **`python run.py --init`** — interactive wizard orchestrating 1 + 2, writing `.env` +
   `config/profile.json`. Non-interactive fallback: hand-edit those two files and run the
   provision script directly.

---

## Changes

### 1. Profile config (`config/settings.py` + new files)

- **New `config/profile.example.json`** (tracked) — generic placeholder values:
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
- **`config/settings.py`**: add a `_load_profile()` helper mirroring the existing
  `_load_local_env()` (L9–23) that reads `config/profile.json` if present. Replace the hardcoded
  literals with `profile.get(...)` values, each keeping a safe generic default:
  - L26–28 `YOUR_NAME` / `YOUR_EMAIL` / `YOUR_BIO`
  - L31 `TARGET_ROLES`, L35 `TARGET_COMPANIES`
  - L185 `RESUME_PATH`, L190 `RESUME_TEMPLATE_PATH` → default `config/resume.docx` (drop the
    owner filename)
  - L199 `AI_PROVIDER` → default `"claude"` (matches CLAUDE.md's documented default)
  - Keep `SKIP_COMPANIES`, `SKIP_COMPANY_KEYWORDS`, and the tuning constants as-is — they are
    generic, reusable defaults, not identity.
- **`config/settings.py:256` `NOTION_DB_ID`** → `os.environ.get("NOTION_DB_ID", "")`. Remove the
  hardcoded literal.

### 2. Notion DB provisioning (`scripts/provision_notion.py` — new)

- Reuse the client constructor from `scripts/utils.py:349` (`_notion()` /
  `NotionClient(auth=NOTION_API_KEY)`).
- `provision(parent_page_id, title="Job Search Tracker") -> new_db_id`: one
  `notion.databases.create(parent={"page_id": ...}, title=..., properties={...})` call defining the
  **full schema** from CLAUDE.md's "Notion database schema" section — crucially the `Status` select
  with **all 14 options listed up front** (Interested, Scraped, Reviewed, Resume Tailored, Applied,
  Outreach Sent, Interview Scheduled, Offer Received, Retry, Disregard, Blacklist, Archived,
  Rejected, Human Review). Defining options at create-time sidesteps the documented "Notion API
  can't add select options on write" limit (which only applies to `pages.update`).
  Include: `Job Title` (title); `Company`, `Location`, `Hiring Manager`, `Notes`,
  `Referral Contact`, `Source`, `Salary Range`, `Missing Keywords` (rich_text); `Job URL`,
  `Tailored Resume Link`, `Hiring Manager LinkedIn` (url); `Date Scraped`, `Posted Date`,
  `Date Applied` (date); `ATS Match Score`, `Applicant Count`, `Scoring Attempts` (number);
  `Sponsorship` (select: yes/no/unknown).
- Runnable standalone: `python scripts/provision_notion.py --parent-page <id>` prints the new DB id
  (the file-fallback path).
- **Validation reuse:** expose `validate_schema(db_id) -> list[str]` (missing props / statuses)
  for `run.py --setup` to replace today's presence-only Notion check.

### 3. Setup wizard (`run.py`)

- New `--init` flag → `init_wizard()`:
  1. If `.env` missing, copy `.env.example` → `.env`.
  2. Prompt (with current-value defaults) for the keys the chosen provider needs plus
     `NOTION_API_KEY` and `APIFY_API_TOKEN`; upsert into `.env` (preserving comments) and
     `os.environ`.
  3. Prompt for profile fields → write `config/profile.json` (seed from `profile.example.json`
     first if missing).
  4. Notion DB: if `NOTION_DB_ID` unset, ask for the shared parent page id, call
     `provision_notion.provision(...)`, persist the returned id to `.env`. Offer to skip if the
     user already has a DB id.
  5. Finish by calling the existing `check_setup()` for a green summary.
- Idempotent / re-runnable (upsert into `.env`, never clobber unrelated lines).
- **Harden `check_setup()` (L56–141):** swap the presence-only `NOTION_DB_ID` check (L97) for
  `provision_notion.validate_schema()` when key + id are set; warn clearly if the id is unset
  ("run `python run.py --init`"). Fix the L22 docstring ("install deps" — it doesn't).

### 4. De-personalize tracked files

- `git rm --cached` (keep local) `config/resume.txt`, `config/Achyuth_Resume.docx`,
  `config/ats_tokens.json`. Add a tracked `config/resume.example.txt` placeholder. Add the real
  resume paths + `config/profile.json` to `.gitignore` (alongside the existing
  `config/gmail_credentials.json` entry).
- Genericize owner references (name, `Iamkach` handle, hardcoded DB id/URL) in `README.md`,
  `SETUP.md`, `.claude/agents/*.md` (pipeline-orchestrator, notion-tracker, resume-tailor),
  `.claude/skills/careerpilot-ai/SKILL.md`, `scripts/stage2_tailor.py` comments,
  `code-changes-management/README.md` — point them at `RESUME_TEMPLATE_PATH` / `NOTION_DB_ID`
  instead of literals.

### 5. `.env.example` + CI + docs

- `.env.example`: add `NOTION_DB_ID=` with a comment (set by `--init`, or your own DB id).
- `.github/workflows/nightly-pipeline.yml`: add `NOTION_DB_ID: ${{ secrets.NOTION_DB_ID }}` and the
  currently-missing `APIFY_API_TOKEN: ${{ secrets.APIFY_API_TOKEN }}` to the env block.
- Rewrite `README.md` "Setup" + `SETUP.md` around `python run.py --init`; keep the manual
  file-fallback path documented for CI/power users. Update `CLAUDE.md`'s schema/setup notes to
  mention the provisioning script and env-sourced `NOTION_DB_ID`.

### 6. Security note (advice, not code)

The local git-ignored `.env` and `config/gmail_credentials.json` hold the owner's **live** keys
(Notion, Apify, OpenAI, Claude Code OAuth, Hunter, Gmail client_secret). They are not committed,
but if this repo or its history is ever published, those keys should be **rotated**.

---

## Files to create / modify

- **New:** `config/profile.example.json`, `scripts/provision_notion.py`, `config/resume.example.txt`
- **Modify:** `config/settings.py` (profile loader + env-source `NOTION_DB_ID`), `run.py`
  (`--init` wizard + hardened `check_setup`), `.env.example`, `.gitignore`,
  `.github/workflows/nightly-pipeline.yml`, `README.md`, `SETUP.md`, `CLAUDE.md`, docs & `.claude/*`
  owner references
- **Untrack (git rm --cached, keep local):** `config/resume.txt`, `config/Achyuth_Resume.docx`,
  `config/ats_tokens.json`

## Verification

1. **Fresh-fork sim:** in a scratch copy, delete `.env` + `config/profile.json`, move the resume
   files aside. Run `python run.py --init` end-to-end with a test Notion integration + a shared
   parent page; confirm it writes `.env` (incl. a fresh `NOTION_DB_ID`) and `config/profile.json`,
   and that a new DB appears with **all 18 properties and all 14 `Status` options**.
2. `python run.py --setup` → all ✓ and the schema validator passes; then break one property in
   Notion and confirm `--setup` reports it missing.
3. **File-fallback path:** hand-write `config/profile.json` + `.env` (no wizard), run
   `python scripts/provision_notion.py --parent-page <id>`, then `python run.py --stage 1` and
   confirm a row lands in the new DB.
4. `git ls-files config/` shows no personal resume or DB id tracked; grep the tree for `Achyuth`,
   `Iamkach`, and the old DB id `2ac0907e...` returns only historical/test-fixture hits.
