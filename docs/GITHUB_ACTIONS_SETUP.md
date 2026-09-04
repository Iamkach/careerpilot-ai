# GitHub Actions Setup Guide

How to run the pipeline unattended, off-hours, via the repo's GitHub Actions workflows —
`.github/workflows/nightly-pipeline.yml` (the scheduled pipeline run) and
`.github/workflows/tests.yml` (CI test gate on push/PR). This is a separate, optional layer on
top of the local setup in `SETUP.md` — do that first; everything here assumes a working local
`python run.py --setup`.

---

## 1. Enable Actions on the repo

Private forks/repos sometimes have Actions disabled by default, or capped by a billing/spending
limit. Before anything else:

1. Go to **Settings → Actions → General** and confirm Actions are allowed to run.
2. Go to **Settings → Billing** and confirm there's no spending limit blocking private-repo
   Actions minutes.

If a workflow run shows `startup_failure` at 0 seconds with no job name ever starting, this is
almost always the cause — the workflow YAML never even gets parsed. A green local `pytest` run
does **not** rule this out; it only proves the suite itself is fine.

---

## 2. Add repo secrets

**Settings → Secrets and variables → Actions → New repository secret.**

| Secret | Required for | Notes |
|---|---|---|
| `NOTION_API_KEY` | always | The integration token — same one from `SETUP.md` step 4 |
| `NOTION_DB_ID` | always | Your tracker DB id. See `docs/RUNTIME_NOTES.md` for a currently-open wiring gap on this repo |
| `ANTHROPIC_API_KEY` | `FAST_PROVIDER=claude` (stage 1 scoring, stage 3 outreach) | Metered, cheap, prompt-cached |
| `CLAUDE_CODE_OAUTH_TOKEN` | `QUALITY_PROVIDER=claude_code` (stage 2 tailor, stage 5/6) | Mint locally with `claude setup-token` (requires Claude Pro/Max) — this is what lets the workflow authenticate to your subscription headlessly |
| `APIFY_API_TOKEN` | `ENABLED_SOURCES` entries `linkedin`/`indeed` | See `docs/RUNTIME_NOTES.md` for a currently-open wiring gap on this repo |

`NOTION_SCRATCH_PAGE_ID` / `NOTION_RESTRICTED_COMPANIES_PAGE_ID` are optional features (see
`CLAUDE.md`) — add them the same way only if you use those features and want them exercised in
the nightly run too.

---

## 3. Why the hybrid provider split

`nightly-pipeline.yml` sets `FAST_PROVIDER=claude` + `QUALITY_PROVIDER=claude_code` rather than
one `AI_PROVIDER`. At midnight (the default cron), nothing is competing for your Claude Code
subscription's 5-hour usage window, so routing the few large/quality calls (stage 2/5/6) through
the subscription is free marginal capacity instead of a scarce resource — while the many small
bulk calls (stage 1/3) stay on the cheap, cached, session-window-independent metered path. See
"Hybrid tiering" in `CLAUDE.md` for the full rationale.

---

## 4. Adjust the schedule

> **Scheduled runs are currently disabled** (2026-09-03). The `schedule:` trigger in
> `nightly-pipeline.yml` is commented out because the nightly cron was firing erratically.
> Re-enable it by uncommenting the two `schedule:`/`- cron:` lines. The workflow can still be
> run on demand via `workflow_dispatch` in the meantime.

The cron in `nightly-pipeline.yml` is UTC with no timezone/DST concept:

```yaml
on:
  # schedule:
  #   - cron: "23 5 * * *"   # 05:23 UTC ≈ 12:23 AM CDT (UTC-5) / 11:23 PM CST (UTC-6)
```

Edit the hour to match your own off-hours window, and remember to shift it again across DST
changes if you care about exact local time. Always use an off-peak minute (e.g. `:23`, `:37`)
rather than `:00` to avoid GitHub Actions top-of-the-hour queue bottlenecks.

The workflow also includes a safety guard (`Guard against daytime queue delay`) that aborts
the job if GitHub Actions queue delays cause it to start during daytime/business hours (between
11:00 UTC and 23:00 UTC, roughly 6 AM to 6 PM CDT). This prevents delayed scheduled runs from
competing with interactive Claude Code sessions or exhausting your daytime rolling quota.
Manual runs (`workflow_dispatch`) bypass this check.

---

## 5. Manual runs (`workflow_dispatch`)

The workflow also accepts a manual trigger from the **Actions** tab → *Nightly job search
pipeline* → *Run workflow*, with a `mode` input:

| `mode` | Runs |
|---|---|
| `full` (default) | `python run.py` then `python run.py --evaluate` |
| `scrape` | `python run.py` (stage 1 + 4) |
| `evaluate` | `python run.py --evaluate` (stage 2 + 3 + 4) |
| `ingest` | `python run.py --ingest` (Notion "Interested" only) |
| `stage2` / `stage3` / `stage4` / `stage5` / `stage6` | that single stage (`stage3`/`stage5` run with `--no-confirm`, since there's no human at the prompt) |

Useful for testing the workflow itself without waiting for the next scheduled fire, or for
running an ad hoc stage off your session-window budget.

---

## Currently outstanding issues

This guide covers how to set things up in general. For the specific issues currently open on
*this* repo's Actions/secrets/integrations (missing workflow secrets, the CI gate not running,
a stale integration) — see **`docs/RUNTIME_NOTES.md`**. Those are ops/infra items, tracked
separately from `docs/TODO.md` (code/development work) since fixing them needs repo Settings
access rather than a code change.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `startup_failure` at 0s, no job name | See [step 1](#1-enable-actions-on-the-repo) — Actions disabled or billing-limited, not a workflow bug |
| Scheduled run fails resolving `NOTION_DB_ID` | See `docs/RUNTIME_NOTES.md` |
| `claude setup-token` / subscription auth fails in CI | Re-mint `CLAUDE_CODE_OAUTH_TOKEN` locally (`claude setup-token`, requires Pro/Max) and update the repo secret — tokens can expire |
| Cron fires at the wrong local time | Cron is UTC only, no DST — see [step 4](#4-adjust-the-schedule) |
