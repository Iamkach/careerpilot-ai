# Stage 1 Scraping Sources — Analysis & Alternatives

Research into replacing the two Apify actors currently wired into `scripts/stage1_scrape.py`.

---

## Current state: two bugs

### 1. `bebity~indeed-scraper` does not exist

`https://apify.com/bebity/indeed-scraper` returns **HTTP 404**. Bebity's Indeed actor was
`bebity/indeed-jobs-scraper` and has since been **deprecated by the developer**.

Because `scrape_indeed()` wraps `_apify_run()` in `except Exception: return []`
(`scripts/stage1_scrape.py:166-169`), every Indeed scrape has been failing **silently** and
contributing zero listings. The only trace is a one-line `✗ Indeed scrape failed` in the log.

**Whatever the current listing volume looks like, it is LinkedIn-only.**

The payload `scrape_indeed()` sends — `position`, `country`, `location`, `maxItems`,
`parseCompanyDetails`, `saveOnlyUniqueItems`, `followApplyRedirects` — is an near-exact match for
**`misceres~indeed-scraper`**'s input schema, which suggests that is the actor this code was
originally written against.

### 2. `bebity~linkedin-jobs-scraper` is a paid rental actor, and the payload likely mismatches

It costs **$29.99/month + usage**, deducted from the prepaid balance after the free trial. This
contradicts two comments in the source:

- `scripts/stage1_scrape.py:35` — "well-maintained, supports maxItems up to 100+"
- `scripts/stage1_scrape.py:40` — "free Apify tier: ~5 CU/month"

Its documented input fields are `title` / `location` / `publishedAt` / `rows` / `workType`. But
`_linkedin_payload_base()` sends `queries` / `timePosted` / `maxItems` / `scrapeCompany` / `cookie`.

`scrapeCompany` and `cookie` are **curious_coder**'s fields. Both
`.claude/agents/pipeline-orchestrator.md:55` and `.claude/commands/scrape.md:8` still document
curious_coder as the actor in use. This reads like a migration that only changed the actor
constant and left the payload builder untouched. **Confirm against a real run before trusting the
LinkedIn numbers.**

> Unrelated but urgent: `config/settings.py:142` has a live `APIFY_API_TOKEN` committed in
> plaintext, and it is in git history. `code-changes-management/README.md:72` already flags this.
> **Rotate it.**

---

## Option A — Alternate Apify actors (minimal change)

### LinkedIn

| Actor | Pricing | Cookie needed | Notes |
|---|---|---|---|
| `valig/linkedin-jobs-scraper` | $0.28–0.40 / 1k | No | Cheapest; returns description, salary, applicant count, recruiter info |
| `practicaltools/linkedin-jobs` | $1 / 1k | No | Minimal, fast |
| `curious_coder/linkedin-jobs-scraper` | $1 / 1k | Optional | 114k users; takes `urls` + `cookie` + `count` + `scrapeCompany` — matches the existing payload fields |
| `chronometrica/linkedin-jobs-scraper` | $1.50 / 1k | No | `fetchJobDetails` for full descriptions; `saveOnlyUniqueItems` built in |
| `bebity/linkedin-jobs-scraper` *(current)* | **$29.99/mo + usage** | No | Rental model |

### Indeed

**`misceres~indeed-scraper`** ($3/1k, pay-per-event) is the maintained successor. The existing
payload should work with one rename: `maxItems` → `maxItemsPerSearch`.

### Recommendation within this option

Switch LinkedIn to `valig~linkedin-jobs-scraper` and Indeed to `misceres~indeed-scraper`.

Valig is roughly **100× cheaper** than the current rental at this volume (25 jobs × a handful of
roles daily), needs no `li_at` cookie, and still exposes the `applicant_count` and `salary_range`
fields that `_pre_filter` and `_parse_salary` depend on — which today only arrive when a Premium
cookie is set. Both are pay-per-result, so a `_pre_filter` that discards most listings costs
nothing extra.

That is two constants and two payload builders in `stage1_scrape.py`. The output-field fallback
chains in `scrape_linkedin()` (`job.get("jobUrl") or job.get("link") or ...`) are already
permissive enough that they will likely survive the swap untouched — though **a live run against
one role is the only way to be sure.** Inspect actual dataset items rather than assuming.

---

## Option B — Non-Apify sources

`_apify_run()` is really just an adapter: role in, `list[dict]` with
`url / title / company / location / description` out. Anything producing that shape can replace it.

### B1. ATS-native JSON APIs — free, keyless, no scraping

Greenhouse, Lever, Ashby, Workable, SmartRecruiters and Recruitee all expose public JSON endpoints
for their customers' job boards. No API key, no OAuth, no proxies, no ToS gray area:

```
https://api.greenhouse.io/v1/boards/{company}/jobs?content=true
https://api.lever.co/v0/postings/{company}?mode=json
https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true
```

These return the **full job description in the payload**, so Stage 1 could cache the JD into the
Notion page body without a second enrichment call, and Stage 2's tailoring gets cleaner input than
a LinkedIn description blob.

- **Lever** supports server-side filtering on `team`, `department`, `location`, `commitment`, `level`.
- **Ashby**'s `includeCompensation=true` gives structured salary — better than what `_parse_salary()`
  reverse-engineers from a string.

**Catch:** company-scoped, not keyword-queryable. You need a company list rather than a search term.
For a targeted search that is arguably a feature — it structurally eliminates the staffing and
consulting firms that `SKIP_COMPANIES` exists to filter out, because those firms do not post client
roles on their own Greenhouse board.

### B2. JobSpy — free, self-hosted, closest to a drop-in

`pip install python-jobspy`. One `scrape_jobs()` call hits LinkedIn, Indeed, Glassdoor, Google Jobs,
ZipRecruiter, Bayt and Naukri concurrently and returns a DataFrame whose columns map almost
one-to-one onto what `scrape_linkedin()` and `scrape_indeed()` already build:

| JobSpy column | Existing dict key |
|---|---|
| `title`, `company`, `job_url`, `description` | `title`, `company`, `url`, `description` |
| `min_amount`, `max_amount`, `interval`, `currency` | `salary_range` (via `_parse_salary`) |
| `date_posted`, `is_remote`, `job_level` | — |

Relevant params: `hours_old` (replaces `timePosted: past24Hours`), `results_wanted` (replaces
`maxItems`), `linkedin_fetch_description=True` for full JDs, `proxies`, `site_name`.

This would collapse both broken actors into a single free dependency.

**Two honest caveats:**

1. The README states plainly that *"LinkedIn is the most restrictive and usually rate limits around
   the 10th page with one IP — proxies are a must basically."* At 25-jobs-per-role volume this is
   probably fine, but it will not scale.
2. Maintenance signal is mixed: PyPI shows `1.1.82` while the GitHub repo's latest tagged release is
   `v1.1.79` from **March 2025**. Not abandoned, not briskly maintained either. And it is a scraper,
   so it breaks when LinkedIn's markup changes — that is the tradeoff against a paid actor whose
   maintainer absorbs that breakage for you.

### B3. Aggregator APIs with free tiers

| Source | Auth | Notes |
|---|---|---|
| **Arbeitnow** | None | Free, keyless, and has a **visa sponsorship filter** at the source |
| **Adzuna** | Free API key | Official, generous free tier, good salary data |
| **JSearch** (OpenWeb Ninja) | Free key, no card | Aggregates Google for Jobs → reaches LinkedIn/Indeed/Glassdoor indirectly |
| **USAJobs** | Free key | Federal roles only |
| **Remotive** | None | Remote-only listings |

Arbeitnow deserves specific attention because `EXCLUDE_NO_SPONSORSHIP = True` is currently
implemented as a **regex sweep over the scraped JD text** — a filter that can only catch postings
that *explicitly say* they will not sponsor, and silently passes through the ones that just do not
mention it. A source that filters on sponsorship server-side is strictly better than that heuristic.

### B4. Managed scraping APIs — probably wrong shape

Bright Data, Oxylabs, Scrapingdog and Nimble sell the proxy and anti-bot layer while you write the
parser. Right answer if you are scraping at scale and getting blocked. For a personal job search it
is the wrong shape — you take on parsing work that Apify actors currently do for you, and pay more
than the $1/1k pay-per-result actors in Option A.

Skip unless JobSpy starts getting blocked.

> Note: **Proxycurl**, formerly the obvious pick in this category, **shut down in July 2025** after
> LinkedIn litigation.

---

## Recommendation

Go **hybrid**, and keep `_apify_run()` as a fallback rather than deleting it.

1. **JobSpy for discovery** — replaces both the $29.99/mo bebity rental and the 404'ing Indeed actor
   with a free dependency, and covers more boards than today.
2. **A small ATS feed reader for a curated company list** — cleanest descriptions, lowest noise,
   costs nothing.

Both write into the same `list[dict]`, so `_pre_filter()`, `score_jobs_batch()` and the Notion
insert path downstream **do not change at all**.

### Concretely

- New `scrape_jobspy(role)` and `scrape_ats(company)` in `scripts/stage1_scrape.py`, both returning
  the existing dict shape.
- New `TARGET_COMPANIES` list in `config/settings.py`, alongside the existing `SKIP_COMPANIES`.
- The `source` field already set on each result (`"linkedin"`, `"indeed"`) gives provenance tracking
  for free — extend to `"jobspy:linkedin"`, `"ats:greenhouse"`, etc.

### Before any of that

Read the drop logs. `scrape_indeed()` has been silently returning `[]` on every run, so the real
baseline for what Stage 1 ingests is unknown.

---

## Sources

- [bebity/linkedin-jobs-scraper](https://apify.com/bebity/linkedin-jobs-scraper)
- [bebity/indeed-jobs-scraper (deprecated)](https://apify.com/bebity/indeed-jobs-scraper)
- [curious_coder/linkedin-jobs-scraper](https://apify.com/curious_coder/linkedin-jobs-scraper)
- [valig/linkedin-jobs-scraper](https://apify.com/valig/linkedin-jobs-scraper)
- [chronometrica/linkedin-jobs-scraper](https://apify.com/chronometrica/linkedin-jobs-scraper)
- [practicaltools/linkedin-jobs](https://apify.com/practicaltools/linkedin-jobs)
- [misceres/indeed-scraper](https://apify.com/misceres/indeed-scraper)
- [Best LinkedIn Scrapers on Apify (2026)](https://use-apify.com/docs/best-apify-actors/best-linkedin-scrapers)
- [JobSpy (speedyapply)](https://github.com/speedyapply/JobSpy)
- [python-jobspy on PyPI](https://pypi.org/project/python-jobspy/)
- [6 ATS Platforms with Public Job Posting APIs](https://fantastic.jobs/article/ats-with-api)
- [Every major ATS has a public JSON API](https://earezki.com/ai-news/2026-07-02-every-major-ats-has-a-public-json-api-for-job-openings-nobody-uses-them/)
- [Arbeitnow Job Board API](https://www.arbeitnow.com/blog/job-board-api)
- [Adzuna developer portal](https://developer.adzuna.com/)
- [JSearch](https://www.openwebninja.com/api/jsearch)
- [Best LinkedIn Scrapers in 2026 (Bright Data)](https://brightdata.com/blog/web-data/best-linkedin-scraping-tools)
