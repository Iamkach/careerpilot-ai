# TODO — open work from the refinement-plans / backlog roadmap

Everything below is verified against code, not doc checkboxes. See `docs/CHANGELOG.md` for
what's already landed. The full spec for the largest remaining item (Step 7) still lives in
`docs/refinement-plans/` and `docs/backlog/` — this file is the index, not a replacement.

## Small, standalone fixes

- **`APIFY_API_TOKEN` still a plaintext literal** — `config/settings.py:185`. Every other key
  (Notion/Anthropic/Gemini/OpenAI) is already `os.environ.get(...)`-sourced; this one was
  missed. Rotate the token in the Apify console, then move it to env. Full story:
  `docs/backlog/step-0-rotate-apify-token.md`.
- **`save_draft()` missing `encoding="utf-8"`** — `scripts/stage3_outreach.py:140`. Latent
  Windows cp1252 crash on non-ASCII contact names (e.g. "José García"). One-line fix.
- **`_notion_update()` bare `except: pass`** — `scripts/utils.py:432`. Should log the real
  Notion exception like `_notion_write_job()` now does, instead of failing silently.
- **Step 3 manual QA never run** — add a real `Interested` row with a live LinkedIn URL, run
  `python run.py --ingest`, confirm it lands on `Scraped` with a real score and cached JD (not
  silently retired). Re-run ingest twice to confirm the `existing_urls` snapshot doesn't treat
  the first run's output as a duplicate of itself.

## Step 7 — Communications subsystem (not started)

Two new stages (LinkedIn leads discovery + Hunter-verified cold email), a new ~22-property
Leads Notion DB, `scripts/credits.py`, a digest refactor, GitHub Actions scheduling. Largest
remaining item in the roadmap — has its own blocking Phase-0 spike (Hunter verification
semantics, `linkedin_handle` support, billing edges, Clearbit keyless autocomplete) that must
run before any Phase 1+ code.

Full spec: `docs/backlog/step-7-communications-subsystem.md` and
`docs/refinement-plans/communications/communications-subsystem.md`.
