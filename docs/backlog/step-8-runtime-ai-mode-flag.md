# Step 8 — Runtime `--ai-mode` flag for `run.py`

**Priority:** P3 — quality-of-life, not blocking any pipeline stage
**Depends on:** none — additive to the shipped `FAST_PROVIDER`/`QUALITY_PROVIDER` design
(Step 5's reliability half; see `../CHANGELOG.md`)
**Size:** XS — one new CLI flag, no new files, no schema/data changes
**Source plan:**
[`refinement-plans/ai-provider/runtime-ai-mode-flag.md`](../refinement-plans/ai-provider/runtime-ai-mode-flag.md)
(full spec — this story is a condensed implementation checklist)

## Context

Choosing fully-metered vs. hybrid vs. fully-subscription AI routing today requires editing
`config/settings.py` or hand-setting `FAST_PROVIDER`/`QUALITY_PROVIDER` env vars before every
run — there's no way to pick the mode per-invocation. The nightly GitHub Actions workflow is
the only place that currently overrides the default (hybrid: `FAST_PROVIDER=claude`,
`QUALITY_PROVIDER=claude_code`).

## What to do

1. **`run.py`** — add `import os`; add `--ai-mode {metered,hybrid,subscription}` to the
   argparse setup in `main()`; right after parsing args (before any lazy `config.settings`
   import), map the flag to `os.environ["FAST_PROVIDER"]` / `os.environ["QUALITY_PROVIDER"]`:
   - `metered` → `claude` / `claude`
   - `hybrid` → `claude` / `claude_code`
   - `subscription` → `claude_code` / `claude_code`
   Omitting the flag must leave today's behavior untouched (including the nightly workflow's
   own env vars).
2. **`config/settings.py`** — update the comment at lines ~199-207 to mention the new flag as
   the interactive equivalent of the env-var override. No logic change.
3. **`CLAUDE.md`** — add the flag to "Common Commands" and a note under "Hybrid tiering".

## Verification

- `python run.py --setup --ai-mode metered|hybrid|subscription` prints the correct resolved
  provider/model routing for each mode (reuses the existing `check_setup()` output).
- `python run.py --setup` with no flag is unchanged.
- Nightly workflow (`.github/workflows/nightly-pipeline.yml`) unaffected — it never passes
  `--ai-mode`.

See the source plan for full code diffs and rationale (why the env-var approach is safe given
`_load_local_env()`'s `setdefault` semantics and `run.py`'s already-lazy `config.settings`
imports).
