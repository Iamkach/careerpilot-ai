# Problem

`discover_tokens()` (`scripts/sources.py:818`) finds a company's ATS board by **guessing its slug
from its display name** — `_slugify()` (`:746`) strips punctuation, then `_probe_greenhouse()` /
`_probe_lever()` / `_probe_ashby()` (`:764`-`:815`) try that one candidate against each board API.

Measured against the author's live cache (`config/ats_tokens.json`, 2026-07-25):

```
100 companies cached · 23 with at least one token
  greenhouse 14 · ashby 9 · lever 1
```

**77 companies are cached as all-null** and, per the 30-day staleness rule (`:830`-`:838`), get
re-probed forever with the same failing guess. The failure mode is structural, not a tuning
problem: a board token is whatever the employer typed into their ATS at signup, and for a large
share of companies that is not their de-punctuated display name (`Block` → `square`, `Meta` →
`facebook`, `Alphabet` → `google`, plus every company whose slug carries a suffix, an
abbreviation, or a legacy name). No amount of slug-normalization fixes a value we are not
entitled to derive.

## The signal we already fetch and discard

Most LinkedIn/Indeed postings are syndicated *from* an employer's ATS board and carry a link back
to it. We already receive that link and throw it away:

- `scrape_indeed()` (`:224`) reads `externalApplyLink` **only as a third-choice fallback** for the
  canonical `url` (`:245`-`:247`). When Indeed supplies a normal `url`, the external link — the
  one pointing at the real board — is dropped on the floor. The actor payload also sets
  `followApplyRedirects: False` (`:234`).
- `scrape_linkedin()` (`:172`) reads `applyUrl` as the last of four `url` candidates (`:184`-`:187`),
  same pattern.

So the pipeline already has, on most runs, a set of **observed, exact, employer-authored board
URLs** that it never looks at. Harvesting them converts token discovery from *guessing* (~23% and
flat) to *observing* (exact, and compounding run over run: today's LinkedIn scrape seeds
tomorrow's free direct-board crawl).

This is the same shape as the existing `discover_tokens()` seeding rule in `_scrape_pass()`
(`scripts/stage1_scrape.py:780`), which already grows the seed list from companies present in
Notion. Step 13 grows the *token* the same way the seed list already grows.

## Investigation findings that re-scoped this story

**Verification spike (2026-07-30, `scripts/spike_step13_apply_url_fields.py`, one live call per
actor, `role="Software Engineer"`, n=10):**

- **LinkedIn (`valig~linkedin-jobs-scraper`) — dead end.** `applyType: "EXTERNAL"` on all 10 items
  confirms these are externally-hosted jobs (the exact population this feature targets), but
  `applyUrl` is present in the schema and **empty on all 10**. `jobUrl`/`companyApplyUrl` also
  empty; `companyUrl` only reaches the LinkedIn company page, not a board. No field in this
  actor's payload carries a board URL — falsified, not just unlikely.
- **Indeed (`misceres~indeed-scraper`) with `followApplyRedirects: False`** — also a dead end.
  `externalApplyLink` populated 4/10, but the *content* is Indeed's own
  `indeed.com/applystart?jk=...` tracking redirect, not the employer's board URL.
- **Indeed with `followApplyRedirects: True`** — the only path with a real signal.
  `externalApplyLink` populated 1/10 at this sample size, but that one resolved to a real,
  harvestable Lever token. Wall time was statistically indistinguishable from the no-redirect run
  (43.6s vs 43.4s at n=10) — too small a sample to trust for the actor-time-cost question.

**Re-scope decision (2026-07-31):** a second data point, `docs/refinement-plans/auto-apply/
sourcing-bottleneck-analysis.md` (a doc explicitly marked "do not re-derive" — now relocated to
`docs/research/sourcing-bottleneck-analysis.md`), ran the same `followApplyRedirects: True`
measurement one day earlier at n=20 and got a materially different answer:

| | sourcing-bottleneck-analysis (2026-07-29, n=20) | this spike (2026-07-30, n=10) |
|---|---|---|
| Wall-clock cost | **+64%** (33.0s → 54.1s / 20 items) | statistically indistinguishable (43.6s vs 43.4s) |
| What the recovered links point to | 4/4 custom career sites — zero Greenhouse/Lever/Ashby/Workday | 1/1 real Lever token |

Both samples are too small to trust on their own, and they disagree on both axes. Rather than run
a third spike to break the tie, the redirect-following path is **parked, not resolved** (see
non-goals.md). Consequence: LinkedIn/Indeed apply-URL harvesting is dropped from scope entirely —
the only remaining harvest source is a board-sourced job's own `url` (a job already sourced via
`greenhouse`/`lever`/`ashby` carries its own board URL as `url`). Parsing it back doesn't discover
a *new* company, but it upgrades an already-correct guessed token to `provenance: "observed"`,
permanently exempting it from the 30-day re-probe. This is real but smaller than originally
promised: it does not touch any of the 77 all-null companies, since none of them have a
board-sourced job to self-confirm from by definition. Growing past that 77 is a different story
(the curated target-companies list, and later Step 15's live-page feed).
