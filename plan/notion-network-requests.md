
▎ Dedup is now an N-network-call loop.

Every scraped candidate job is checked for "do we already have this in Notion?" by calling db_find_job_by_url() — and that helper runs a paginated Notion API query each time. In stage1_scrape.py:

- The per-job dedup lives inside _pre_filter() at line 510 (if db_find_job_by_url(url):).
- _pre_filter() is called once per raw listing in the loop at line 552, for every role in TARGET_ROLES.

So with ~2 sources (LinkedIn + Indeed) × ~25 listings each × several target roles, you fire 100+ sequential network round-trips to Notion just to detect duplicates — against Notion's ~3 requests/second rate limit. That makes Stage 1 slow and risks throttling.

Note the seen_urls set at line 536 only dedups within the current run (line 549), so it doesn't help against jobs already stored in Notion from previous runs — that's what the Notion query is for.

The suggested fix: fetch all existing job URLs from Notion once at the start of run() into a set, then have _pre_filter() do an in-memory url in existing_urls check instead of a per-job query. That collapses 100+ queries down to a handful of paginated reads.

my idea - when all existing urls are fetched at once at start, I want to fetch full columns of each row and save in a temp file like a csv. So that I can use it for other tasks. this file can be deleted after workflow or run completion
