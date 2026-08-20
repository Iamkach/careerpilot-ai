# Problem

Today there is no scheduling infrastructure, no contact-data source, no Leads store, and no digest
section primitive for outreach beyond the existing warm-referral flow. This is largely greenfield.

**Governing rule: APIs supply facts; AI ranks and writes** — the AI never invents a name, title,
email, or domain; a code-level validator enforces this, not the prompt.

## Sources: chosen and rejected

| Source | Verdict |
|---|---|
| **Hunter.io** — Email Finder, Email Verifier, Domain Search | **Core.** Domain Search returns *people* (name, title, seniority, department, LinkedIn, confidence), not just addresses, and accepts a `company` name. Covers prong 2 end-to-end, no scraping. |
| **Apify `coregent~linkedin-recruiter-job-poster-finder`** | **Core, narrow.** Uses LinkedIn's public guest job endpoints — no `li_at` cookie, so ban risk lands on the actor's proxies, not the account. ~$2.40/1k unique leads; person-less jobs/duplicates not billed. Only viable way to learn who posted a *specific* req. |
| `apt_marble~linkedin-recruiter-scraper` | **Fallback only.** $1.50/1k, no-cookie, but returns recruiters unattached to a job (no `job_url`, no join). Prefer coregent. |
| Apollo.io | **Rejected.** Free People Search obfuscates `last_name`, which breaks Email Finder (needs a full name). |
| People Data Labs | **Rejected.** 100 lookups/mo, email fields gated behind paid access. |
| Clearbit enrichment | **Rejected** as a primary source (free tier sunset April 2025) — its keyless *autocomplete* endpoint is used opportunistically for company→domain only, never depended on. |
| Proxycurl | **Rejected.** Shut down July 2025. |
| Scraping LinkedIn's guest endpoint directly | **Rejected.** Brittle, IP-blocked, worse ToS posture than a vendor that absorbs it. |

Apify is not eliminated — reduced to the one job (per-req poster identity) it alone can do.
`valig~linkedin-jobs-scraper` (already swapped in for Step 1/6 cost reasons) returns
`recruiterName`/`recruiterUrl` with no cookie, so **prong 1's job-linked contact data arrives free
as a side effect of scraping**, no second actor needed for that half.
