# Step 13 — Board-token harvesting (observe ATS boards instead of guessing them)

**Status:** finalized, queued, **not started.**
**Priority:** P2 — nothing is broken, but ATS-board coverage is stuck at ~23% and cannot improve
on its own. Every run pays LinkedIn/Indeed actor cost for jobs whose employer board we could be
crawling for free.
**Depends on:** Step 6 (`scripts/sources.py` registries, `discover_tokens()`, `config/ats_tokens.json`)
— landed. No Notion schema change in Phase 1.
**Size:** **S** for Phase 1 (the whole value), M for Phases 2–3.

---

## The problem

`discover_tokens()` (`scripts/sources.py:818`) finds a company's ATS board by **guessing its slug
from its display name** — `_slugify()` (`:746`) strips punctuation, then `_probe_greenhouse()` /
`_probe_lever()` / `_probe_ashby()` (`:764`–`:815`) try that one candidate against each board API.

Measured against the author's live cache (`config/ats_tokens.json`, 2026-07-25):

```
100 companies cached · 23 with at least one token
  greenhouse 14 · ashby 9 · lever 1
```

**77 companies are cached as all-null** and, per the 30-day staleness rule (`:830`–`:838`), get
re-probed forever with the same failing guess. The failure mode is structural, not a tuning
problem: a board token is whatever the employer typed into their ATS at signup, and for a large
share of companies that is not their de-punctuated display name (`Block` → `square`, `Meta` →
`facebook`, `Alphabet` → `google`, plus every company whose slug carries a suffix, an
abbreviation, or a legacy name). No amount of slug-normalization fixes a value we are not
entitled to derive.

### The signal we already fetch and discard

Most LinkedIn/Indeed postings are syndicated *from* an employer's ATS board and carry a link back
to it. We already receive that link and throw it away:

- `scrape_indeed()` (`:224`) reads `externalApplyLink` **only as a third-choice fallback** for the
  canonical `url` (`:245`–`:247`). When Indeed supplies a normal `url`, the external link — the
  one pointing at the real board — is dropped on the floor. The actor payload also sets
  `followApplyRedirects: False` (`:234`).
- `scrape_linkedin()` (`:172`) reads `applyUrl` as the last of four `url` candidates (`:184`–`:187`),
  same pattern.

So the pipeline already has, on most runs, a set of **observed, exact, employer-authored board
URLs** that it never looks at. Harvesting them converts token discovery from *guessing* (~23% and
flat) to *observing* (exact, and compounding run over run: today's LinkedIn scrape seeds
tomorrow's free direct-board crawl).

This is the same shape as the existing `discover_tokens()` seeding rule in `_scrape_pass()`
(`scripts/stage1_scrape.py:780`), which already grows the seed list from companies present in
Notion. Step 13 grows the *token* the same way the seed list already grows.

---

## Binding decisions

1. **Observation beats verification-by-probe, and the code must record which it had.**
   `config/ats_tokens.json` entries gain a `provenance` field: `"observed"` (parsed out of a real
   posting URL) or `"guessed"` (today's `_slugify()` probe). Greenhouse stays probe-verified either
   way — `_probe_greenhouse()` checks `jobs[0].company_name` and is cheap. Lever and Ashby expose
   no company field, which is exactly why `_probe_lever()`/`_probe_ashby()` log the loud
   `⚠ AUTO-ACCEPTED … unverifiable` warning today. **An observed Lever/Ashby token does not get
   that warning** — it did not come from a guess, so there is nothing for the user to veto.

2. **Never re-guess a company that has an observed token.** `discover_tokens()` currently skips any
   company with ≥1 hit (`:840`) and re-probes all-null entries after 30 days. Add: skip probing
   entirely when `provenance == "observed"`, and let observation overwrite a `"guessed"` token
   (observation is strictly better evidence).

3. **Phase 1 makes zero new network calls.** The harvest reads fields already present in the Apify
   response. This is what keeps it S-sized and makes it safe to land before knowing the hit rate.

4. **Do not follow LinkedIn apply redirects.** LinkedIn's apply link sits behind an authwall;
   resolving it requires an authenticated session — the precise ToS/behavioral-detection surface
   that `FILLABLE_CHANNELS` (`scripts/autoapply.py:106`) excludes LinkedIn from **by rule, not by
   configuration**. Step 13 must not reintroduce it through a side door. Indeed's
   `followApplyRedirects: True` is the legitimate escape hatch and is deferred to Phase 2, since it
   costs actor time on every job.

5. **Record boards we cannot crawl.** A Workday/iCIMS URL still answers the question the user
   actually asked — "which board does this company use" — even where no crawlable API exists.
   Recording it is nearly free and is what tells us whether Phase 3 is worth building.

6. **`config/ats_tokens.json` is git-ignored** (`.gitignore:27`, untracked by Step 11 §2c). The
   registry is therefore **per-fork local state** — a fresh clone starts at zero and re-earns its
   tokens. Accepted for Phases 1–3; mirroring to Notion is listed under "Deferred" below.

---

## Phase 1 — harvest from data already fetched (the whole value; S)

### 1a. Carry the apply URL on the job dict

`scripts/sources.py` — `scrape_linkedin()` (`:205`) and `scrape_indeed()` (`:251`) each add one key
to the emitted dict:

```python
"apply_url": job.get("externalApplyLink") or job.get("applyUrl")
             or job.get("companyApplyUrl") or "",
```

Purely additive. Every downstream consumer (`collapse_by_fingerprint`, `_pre_filter`,
`_notion_write_job`) reads named keys, so an extra key is inert — **no other call site changes.**

> **Unverified assumption — check first.** The exact field names each actor returns are inferred
> from the existing `url`-fallback chains (`:184`–`:187`, `:245`–`:247`), not from a captured
> payload. Before writing 1b, dump one real `_apify_run()` response per actor and confirm which of
> `externalApplyLink` / `applyUrl` / `companyApplyUrl` is actually populated and how often. **If
> the harvest rate is near zero, stop — Phase 1's premise is wrong** and the fallback is Phase 2's
> `followApplyRedirects`, not more parsing.

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
- **Reuse, don't duplicate:** `parse_greenhouse_url()` (`scripts/autoapply.py:125`) already handles
  all three Greenhouse shapes including the `embed/job_app` variant. Either import it or lift the
  shared parsing into `sources.py` and have `autoapply` import from there — do **not** write a
  second Greenhouse URL parser that can drift from the first.
- Pure function, no I/O → unit-testable with a table of real URLs and lookalikes.

### 1c. `harvest_board_tokens(jobs) -> dict`

New function in `scripts/sources.py`, next to `discover_tokens()`. For each job, run
`parse_board_url()` over its `apply_url` **and** its `url` (an ATS-sourced job's own `url` is
already a board URL — free confirmation of a token we may only have guessed). On a hit, merge into
the loaded token cache under the job's `company`:

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
decision 1. Writes via the existing `_save_tokens()` (`:759`) — one file write per run, not per job.

### 1d. Wire into stage 1

`scripts/stage1_scrape.py`, `_scrape_pass()` — call `harvest_board_tokens(raw_jobs)` **after the
global gather** (after the board-source loop ends at `:788`, before `collapse_by_fingerprint()` at
`:794`). Ordering matters and is non-obvious:

- **After the gather**, so board-sourced jobs contribute their own URLs as confirmation.
- **Before the collapse**, because `collapse_by_fingerprint()` (`:717`) *discards* the LinkedIn
  copy of a duplicate in favour of the ATS copy (`SOURCE_PRIORITY`, `:676`). Harvesting after the
  collapse would silently throw away exactly the LinkedIn/Indeed rows this feature exists to read.
- Tokens harvested this run take effect **next** run — `discover_tokens()` has already run by this
  point (`:782`). That is fine and deliberate: making it same-run would mean a second gather pass.
  Log the count so the compounding effect is visible (`Harvested N board token(s) — active next run`).

### 1e. Teach `discover_tokens()` about provenance

`scripts/sources.py:818` — in the skip logic at `:826`–`:840`: treat `provenance == "observed"` as
a permanent skip (never re-probe, regardless of the 30-day staleness rule). Leave the existing
guessed-token behaviour otherwise unchanged.

**Back-compat:** existing cache entries have no `provenance` key. `entry.get("provenance", "guessed")`
makes every current entry read as a guess, which is correct and needs no migration.

### 1f. Tests (`tests/test_sources_board_harvest.py`, new)

Follows the existing pure-function contract-test pattern in `tests/test_sources.py` — no API keys,
no network, monkeypatch `ATS_TOKENS_PATH` to a `tmp_path`.

- `parse_board_url()` table: all three Greenhouse shapes, Lever, Ashby, each returning the right
  token; **lookalike hosts** (`evilgreenhouse.io`, `notlever.co`, `acme.com/?x=jobs.lever.co`) must
  return `None` — this is the security-relevant case and mirrors the assertion
  `tests/test_autoapply_plan.py` already makes for `detect_apply_channel()`.
- `harvest_board_tokens()`: observed beats guessed; guessed never overwrites observed; a job with
  no `apply_url` and a non-board `url` is a no-op; a Greenhouse observation whose probe fails is
  **not** written.
- `discover_tokens()` skips an `"observed"` entry even when `checked` is >30 days old.
- Cache entries lacking `provenance` still behave exactly as today (back-compat).

---

## Phase 2 — record the boards we cannot crawl (M)

Extend `parse_board_url()` to recognize, and `harvest_board_tokens()` to record under a separate
`"other"` key (registry entry only — **no** `BOARD_SOURCES` crawl):

`{tenant}.wd{N}.myworkdayjobs.com` · `jobs.smartrecruiters.com/{token}` ·
`apply.workable.com/{token}` · `careers.icims.com` · `{co}.recruitee.com` · `{co}.bamboohr.com/careers`

Also in scope if Phase 1's harvest rate proves thin: flip Indeed's `followApplyRedirects` to `True`
(`scripts/sources.py:234`) so Indeed resolves the redirect for us. Gate it behind a setting and
measure the actor-time cost — this is the *only* sanctioned redirect-following path (decision 4).

**Output of this phase is data, not capability**: after a few nightly runs the registry answers
"which ATS does each of my target companies use", which is what makes the Phase 3 build/skip call
evidence-based instead of speculative.

---

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
`_probe_*`/parse pair — mechanically identical to `greenhouse_source()` (`:279`). **No stage-1
changes**: the registry loop at `:783`–`:788` already iterates whatever `BOARD_SOURCES` contains.

**Trigger:** build a provider only once Phase 2 data shows ≥5 tracked companies on it. Below that,
the Apify path is cheaper than the code.

---

## Deferred (not in scope)

- **Mirroring the registry to Notion.** Split out into
  `docs/backlog/step-14-target-companies-notion.md` (queued separately, scoped to the curated
  target-company list rather than the full harvested registry) rather than tracked here.
- **Careers-page crawling for companies with no observed URL** (fetch `{company}.com/careers`, look
  for ATS links). A real per-company network cost with a `max_new_probes`-style budget; only worth
  it if Phases 1–2 leave a large gap.
- **Following LinkedIn apply redirects** — excluded by rule, see decision 4. Not deferred; rejected.

---

## Verification

1. **Before writing 1b:** dump one real `_apify_run()` response per actor; confirm which apply-URL
   field is populated and estimate the harvest rate. Near-zero ⇒ stop and reconsider (see 1a).
2. `pytest -v` green, including `tests/test_sources_board_harvest.py`. No API keys, no network.
3. Back up `config/ats_tokens.json`, run `python run.py --stage 1`, then diff: new/changed entries
   should carry `provenance: "observed"`, and no existing token should be downgraded to a guess.
4. Confirm the log line reports a non-zero harvest count, and that a company newly given an
   observed token is crawled via `BOARD_SOURCES` on the **next** run (per 1d's ordering note).
5. Re-measure the cache after ~5 nightly runs. The number that decides Phase 2/3 is the
   observed-token count versus today's baseline of **23 / 100**.

## Files

- **Modify:** `scripts/sources.py` — `scrape_linkedin()`, `scrape_indeed()` (1a); new
  `parse_board_url()`, `harvest_board_tokens()` (1b/1c); `discover_tokens()` provenance skip (1e)
- **Modify:** `scripts/stage1_scrape.py` — `_scrape_pass()` harvest call + import (1d)
- **Modify (maybe):** `scripts/autoapply.py` — if `parse_greenhouse_url()` moves to `sources.py`
  rather than being imported (1b)
- **New:** `tests/test_sources_board_harvest.py` (1f)
- **Modify:** `CLAUDE.md` — the "Multi-source sourcing" section's `discover_tokens()` paragraph
  gains the observe-vs-guess distinction and the `provenance` field
- **No change:** Notion schema, `config/settings.py` (Phase 1 introduces no new setting)
