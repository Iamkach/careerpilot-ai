# Plan

## Phase 1

### 1a. (dropped)

LinkedIn/Indeed apply-URL harvesting is out of scope — see problem.md's "Investigation findings."
Re-open only if a future Apify actor version, a different LinkedIn payload shape, or a resolved
`followApplyRedirects` cost question changes the evidence.

### 1b. `parse_board_url(url) -> tuple[str, str] | None`

New pure function in `scripts/sources.py`, next to `host_matches()` (`:638`). Given any URL,
return `(ats_name, token)` or `None`.

- **Host match via the existing `host_matches()`** — a real label-boundary check, so
  `evilgreenhouse.io` does not route as Greenhouse. This is the same hardening
  `detect_apply_channel()` (`scripts/autoapply.py:109`) already documents; do not hand-roll a
  second `endswith()`.
- Crawlable today (feeds `BOARD_SOURCES`):
  | ATS | URL shapes | Token |
  |---|---|---|
  | greenhouse | `boards.greenhouse.io/{t}/jobs/{id}`, `job-boards.greenhouse.io/{t}/…`, `boards.greenhouse.io/embed/job_app?for={t}` | `{t}` |
  | lever | `jobs.lever.co/{t}/{id}` | `{t}` |
  | ashby | `jobs.ashbyhq.com/{t}/{id}` | `{t}` |
- **Canonical location: `sources.py`, not `autoapply.py`.** `parse_greenhouse_url()`
  (`scripts/autoapply.py:125`) already handles all three Greenhouse shapes including the
  `embed/job_app` variant. `sources.py` already owns `BOARD_SOURCES`/`host_matches()`/token
  parsing, so its logic moves into `parse_board_url()` here and `autoapply.py` imports the shared
  function instead of keeping its own — do **not** write a second Greenhouse URL parser that can
  drift from the first. No call-site signature changes in `autoapply.py`.
- Pure function, no I/O → unit-testable with a table of real URLs and lookalikes.

### 1c. `harvest_board_tokens(jobs) -> dict`

New function in `scripts/sources.py`, next to `discover_tokens()`. For each job, run
`parse_board_url()` over its `url` (an ATS-sourced job's own `url` **is** its board URL — free
confirmation of a token we may only have guessed). On a hit, merge into the loaded token cache
under the job's `company`:

```json
"Abridge": {
  "greenhouse": null, "lever": null, "ashby": "abridge",
  "provenance": "observed",
  "observed_from": "https://jobs.ashbyhq.com/abridge/…",
  "checked": "2026-07-25"
}
```

Rules: an observed token overwrites a `"guessed"` one and is never overwritten by a guess; a
Greenhouse observation is still confirmed with `_probe_greenhouse()` before being written (cheap
and verifiable); Lever/Ashby observations are written without the `⚠ AUTO-ACCEPTED` warning per
constraints.md #1. Writes via the existing `_save_tokens()` (`:759`) — one file write per run, not
per job.

### 1d. Wire into stage 1

`scripts/stage1_scrape.py`, `_scrape_pass()` — call `harvest_board_tokens(raw_jobs)` **after the
global gather** (after the board-source loop ends at `:788`, before `collapse_by_fingerprint()` at
`:794`) — see constraints.md #7 for why the ordering matters. Log the count so the compounding
effect is visible (`Harvested N board token(s) — active next run`).

### 1e. Teach `discover_tokens()` about provenance

`scripts/sources.py:818` — in the skip logic at `:826`-`:840`: treat `provenance == "observed"` as
a permanent skip (never re-probe, regardless of the 30-day staleness rule). Leave the existing
guessed-token behaviour otherwise unchanged.

### 1f. Tests (`tests/test_sources_board_harvest.py`, new)

Follows the existing pure-function contract-test pattern in `tests/test_sources.py` — no API keys,
no network, monkeypatch `ATS_TOKENS_PATH` to a `tmp_path`. See acceptance-criteria.md for the
exact cases.

## Phase 2 — record the boards we cannot crawl (M)

Extend `parse_board_url()` to recognize, and `harvest_board_tokens()` to record under a separate
`"other"` key (registry entry only — **no** `BOARD_SOURCES` crawl):

`{tenant}.wd{N}.myworkdayjobs.com` · `jobs.smartrecruiters.com/{token}` ·
`apply.workable.com/{token}` · `careers.icims.com` · `{co}.recruitee.com` · `{co}.bamboohr.com/careers`

Output of this phase is data, not capability: after a few nightly runs the registry answers
"which ATS does each of my target companies use", which is what makes the Phase 3 build/skip call
evidence-based instead of speculative.

## Phase 3 — new `BOARD_SOURCES` entries (M, gated on Phase 2 data)

Ranked strictly by whether a **public, keyless JSON API** actually exists — the property that made
Greenhouse/Lever/Ashby cheap in Step 6:

| Provider | Public keyless JSON API | Verdict |
|---|---|---|
| **SmartRecruiters** | Yes — `api.smartrecruiters.com/v1/companies/{id}/postings` | Best next `BOARD_SOURCES` entry |
| **Workable** | Yes — `apply.workable.com/api/v1/widget/accounts/{token}?details=true` | Good second |
| **Workday** | Semi — `POST /wday/cxs/{tenant}/{site}/jobs`; needs the per-company `{site}` path, brittle | Record only. `CHANNEL_POLICY` (`scripts/autoapply.py:95`) already treats Workday as assisted-only; do not build a crawler for a channel we cannot fill. |
| **iCIMS / Taleo / BrassRing** | No | Record the board URL; apply by hand |

Each new entry is a `fn(company, token) -> list[dict]` returning the standard source dict, plus a
`SOURCE_PRIORITY` rank (below the three existing ATS boards, above `linkedin`), plus a
`_probe_*`/parse pair — mechanically identical to `greenhouse_source()` (`:279`). No stage-1
changes: the registry loop at `:783`-`:788` already iterates whatever `BOARD_SOURCES` contains.

**Trigger:** build a provider only once Phase 2 data shows ≥5 tracked companies on it.

## Files

- **Modify:** `scripts/sources.py` — new `parse_board_url()` (absorbs `autoapply.py`'s
  `parse_greenhouse_url()`), `harvest_board_tokens()` (1b/1c); `discover_tokens()` provenance
  skip (1e)
- **Modify:** `scripts/stage1_scrape.py` — `_scrape_pass()` harvest call + import (1d)
- **Modify:** `scripts/autoapply.py` — `parse_greenhouse_url()` removed, imports the shared
  function from `scripts.sources` instead (1b)
- **New:** `tests/test_sources_board_harvest.py` (1f)
- **Modify:** `CLAUDE.md` — the "Multi-source sourcing" section's `discover_tokens()` paragraph
  gains the observe-vs-guess distinction and the `provenance` field, described honestly as
  self-confirmation of board-sourced jobs' own URLs, not a new-coverage mechanism
- **No change:** Notion schema, `config/settings.py` (Phase 1 introduces no new setting),
  `scripts/sources.py`'s `scrape_linkedin()` / `scrape_indeed()` (apply-URL harvesting dropped)
