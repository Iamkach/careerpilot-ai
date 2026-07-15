# Runtime `--ai-mode` flag for `run.py`

**Status:** not started
**Depends on:** none — additive to the existing `FAST_PROVIDER`/`QUALITY_PROVIDER` design
(Step 5's hybrid-agentic-migration reliability half; see `../../CHANGELOG.md`)

## Problem

The metered-vs-hybrid-vs-subscription choice is currently baked into config at two layers:

- `AI_PROVIDER` in `config/settings.py` (default `"claude"` — fully metered)
- `FAST_PROVIDER` / `QUALITY_PROVIDER` env-var overrides (`config/settings.py:208-209`),
  which only `.github/workflows/nightly-pipeline.yml` currently sets
  (`FAST_PROVIDER=claude`, `QUALITY_PROVIDER=claude_code` — a hybrid split)

A local/interactive user who wants to try hybrid or full-subscription mode today has to
hand-set env vars or edit `config/settings.py` before every run, and revert it back
afterward. There's no way to pick the mode per-invocation.

## How provider resolution works today (for context)

`scripts/utils.py:_active_provider(quality)` resolves the provider per AI call: it prefers
`FAST_PROVIDER`/`QUALITY_PROVIDER` when either differs from `AI_PROVIDER`, else falls
through to `STAGE_AI_PROVIDER` then `AI_PROVIDER`. `config/settings.py:208-209` sets
`FAST_PROVIDER`/`QUALITY_PROVIDER` from `os.environ.get(...)` **at import time**, and
`_load_local_env()` (`config/settings.py:9-23`) uses `os.environ.setdefault(...)` to load
`.env` — meaning a real env var set before `config.settings` is first imported always wins
over both `.env` and the hardcoded default.

All of `run.py`'s `config.settings` imports are already lazy (inside function bodies:
`check_setup()`, `stage1`..`stage6`, `ingest_routine`, `morning_routine`,
`evaluate_routine` — none at module top level). So the cleanest runtime toggle is a CLI flag
that sets `FAST_PROVIDER`/`QUALITY_PROVIDER` env vars before any of those functions run — no
changes needed to `scripts/utils.py`'s resolution logic at all.

## Proposed change

### 1. `run.py` — add `--ai-mode` CLI flag

In `main()` (`run.py:219-238`), add:

```python
parser.add_argument(
    "--ai-mode", type=str, default=None,
    choices=["metered", "hybrid", "subscription"],
    help="Override AI provider routing for this run: "
         "metered = claude everywhere (default config behavior), "
         "hybrid = claude for fast/bulk calls + claude_code (subscription) for quality calls, "
         "subscription = claude_code everywhere",
)
```

Right after `args = parser.parse_args()`, and before `sys.path.insert` / any stage or
`check_setup()` call, translate the flag to env vars — only when the user actually passed
it, so omitting `--ai-mode` preserves today's behavior exactly (including the nightly
workflow's own env vars):

```python
_AI_MODE_PROVIDERS = {
    "metered":      ("claude",      "claude"),
    "hybrid":       ("claude",      "claude_code"),
    "subscription": ("claude_code", "claude_code"),
}
if args.ai_mode:
    fast, quality = _AI_MODE_PROVIDERS[args.ai_mode]
    os.environ["FAST_PROVIDER"] = fast
    os.environ["QUALITY_PROVIDER"] = quality
```

Requires adding `import os` to `run.py`'s existing `import sys, argparse, subprocess` line.

This must execute before the first `config.settings` import anywhere in the process — placing
it at the top of `main()`, before any stage/`check_setup()` call, satisfies that (Python
caches the module on first import).

### 2. `--setup` output already reflects it, no change needed

`check_setup()` (`run.py:49-132`) already prints the resolved `FAST_PROVIDER`/
`QUALITY_PROVIDER` and their models (`run.py:76-83`). Since the env vars are set before
`check_setup()` reads `config.settings`, `python run.py --setup --ai-mode hybrid` will
already reflect the override correctly with zero changes there.

### 3. `config/settings.py` — comment update only

Update the comment block at `config/settings.py:199-207` (currently frames the env override
as CI-only: "e.g. for an unattended nightly GitHub Actions run") to also mention
`python run.py --ai-mode {metered,hybrid,subscription}` as the interactive way to set the
same env vars for a single run, so the config file and the CLI stay in sync as documentation.
No logic change.

### 4. `CLAUDE.md` — document the new flag

Add `--ai-mode {metered,hybrid,subscription}` to the "Common Commands" list, and a short note
under "Switching AI Provider" / "Hybrid tiering" explaining it's a per-invocation override of
`FAST_PROVIDER`/`QUALITY_PROVIDER` that takes precedence over `.env` for that single process
and does not persist — the next run without the flag reverts to config defaults (including the
nightly workflow, which never passes it and keeps its own env vars).

## Files touched

- `run.py` — `import os`, the `--ai-mode` argument, `_AI_MODE_PROVIDERS` mapping + env-var
  assignment in `main()`
- `config/settings.py` — comment update only (~lines 199-207)
- `CLAUDE.md` — document the new flag

No changes to `scripts/utils.py` or Notion/stage logic.

## Verification

1. `python run.py --setup --ai-mode metered` → prints `AI provider : claude (fast: ...,
   quality: ...)`.
2. `python run.py --setup --ai-mode hybrid` → prints `AI routing  : fast=claude (...) |
   quality=claude_code (...)`.
3. `python run.py --setup --ai-mode subscription` → prints `AI provider : claude_code (...)`,
   and (if the `claude` CLI isn't logged in) the `_provider_key` check correctly flags the
   missing CLI/login rather than checking `ANTHROPIC_API_KEY`.
4. `python run.py --setup` (no flag) → unchanged from current behavior.
5. Confirm no regression to the nightly workflow: since it never passes `--ai-mode`, its own
   `FAST_PROVIDER=claude` / `QUALITY_PROVIDER=claude_code` env vars (set in the workflow YAML)
   still take effect unchanged.
