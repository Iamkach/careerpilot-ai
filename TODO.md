# Pipeline Reliability, Filtering, and Networking Sourcing - TODO

## Section 1: AI-Call Reliability (Subscription vs API)

### Default Configuration
- [ ] Change `AI_PROVIDER` default from `"claude_code"` to `"claude"` in `config/settings.py` (line 125)
- [ ] Document in `config/settings.py` that `STAGE_AI_PROVIDER` can override `AI_PROVIDER` for stage scripts

### Retry & Backoff Logic
- [ ] Add retry-with-backoff wrapper for `workflow.py`'s `query()` loop in `_run()` (lines 781-816)
  - [ ] Implement 3 attempts with exponential backoff (2s, 4s, 8s)
  - [ ] Handle transient errors: rate limit, 5xx, timeout
  - [ ] Distinguish usage-cap-exceeded error and fail with clear "wait for renewal" message
- [ ] Add same retry logic to each `_chat_*` backend in `scripts/utils.py`
- [ ] Add retry logic around `score_jobs_batch()` AI call in `scripts/stage1_scrape.py`
- [ ] Add retry logic around InMail/outreach AI calls in `scripts/stage3_outreach.py`

### Exception Handling & User Guidance
- [ ] Wrap `_run()` loop body in try/except to capture partial progress
- [ ] Print job/tool-call completion count before failure
- [ ] Add message: "Re-running is safe and will skip completed work (using existing idempotency)"
- [ ] Apply same pattern to exception handling in `stage1_scrape.py` and `stage3_outreach.py`

### Verification for §1
- [ ] Force transient error during `workflow.py` run and confirm retry/backoff engages
- [ ] Verify failure message distinguishes usage-cap error from transient error
- [ ] Run interrupted workflow and confirm already-processed jobs are skipped

---

## Section 2: Better Filtering (Product Companies, Real Sponsorship)

### Company-Type AI Classification
- [ ] Extend `score_jobs_batch()` JSON schema in `scripts/stage1_scrape.py` (lines 322-381)
  - [ ] Add `company_type: product | staffing_or_consulting | agency | unknown` field
  - [ ] Use company/JD text already in prompt (no extra API call)
- [ ] Implement drop logic for `company_type == "staffing_or_consulting"` (mirror line 570-572 pattern)
- [ ] Log drop reason via existing `_log_drop()` function

### Fix False Positives
- [ ] Remove `"Qualcomm"` from `SKIP_COMPANIES` in `config/settings.py` (line 43)
- [ ] Audit remaining `SKIP_COMPANIES` list (settings.py:22-44) for similar false positives

### Sponsorship Ambiguity Handling
- [ ] Add Notion property to surface sponsorship value and reason (for visibility of "unknown" cases)
- [ ] Add `SPONSORSHIP_MODE` setting to `config/settings.py`: `"lenient" | "strict"`
  - [ ] In `"strict"` mode, drop jobs where `sponsorship == "unknown"`
  - [ ] In `"lenient"` mode, pass through "unknown" sponsorship jobs

### Dead Config Cleanup
- [ ] Remove or document `TARGET_COMPANIES` in `config/settings.py` (currently unused in `stage1_scrape.py`)

### Files to Modify
- [ ] `config/settings.py`
- [ ] `scripts/stage1_scrape.py`

### Verification for §2
- [ ] Run `python run.py --stage 1` with small `max_results`
- [ ] Confirm known staffing/consulting company (not in `SKIP_COMPANIES`) caught by new AI classification
- [ ] Confirm `"Qualcomm"` no longer gets dropped
- [ ] Confirm sponsorship `"unknown"` jobs visible with reason in Notion

---

## Section 3: Networking-Based Sourcing (Hiring Managers, Recruiters, "We're Hiring" Posts)

### Research & Discovery
- [ ] **SPIKE:** Identify and validate working Apify actor for LinkedIn post/people search
  - [ ] Verify pricing, output schema, and Terms of Service compliance
  - [ ] Document actor ID, input parameters, and output fields
  - [ ] Assess rate-limit and ToS risk (LinkedIn restricts profile/activity scraping more than job listings)

### New Sourcing Stage
- [ ] Create `scripts/stage7_network_sourcing.py` using `_apify_run()` pattern from `stage1_scrape.py`
  - [ ] Search for hiring-signal posts ("we're hiring", "join our team", referral asks)
  - [ ] Filter by target companies/roles
  - [ ] Extract: poster name, headline, company, post text/URL
- [ ] Implement poster role classification
  - [ ] Use regex first pass on headline (recruiter/technical recruiter/hiring manager/engineer)
  - [ ] Fall back to LLM classification for ambiguous cases (extend batched AI call)
- [ ] Cross-check poster company against product-company filter
  - [ ] Reuse `is_skipped_company()` + new `company_type` classification from §2

### Notion "Leads" Database
- [ ] Create separate Notion database with distinct schema:
  - [ ] Fields: Name, Title, Company, LinkedIn URL, Post URL/snippet, Status
  - [ ] Status values: `Identified → Approved → Messaged → Replied → Connected`
- [ ] Implement property-mapping using existing `_notion_write_job()`/`_EXTRA_TO_NOTION` pattern in `scripts/utils.py`
- [ ] Set default status to `Identified` (never auto-approved)

### Manual Approval Gate & Outreach
- [ ] Add `draft_connection_request(lead)` function to `scripts/stage3_outreach.py`
  - [ ] Reuse `draft_warm_referral()`'s contact-name-aware AI-drafting pattern (lines 36-48)
  - [ ] Only run for leads marked `Approved` in Notion
  - [ ] Save draft to `output/outreach/` for manual review/send
  - [ ] **Never auto-message or auto-connect**
- [ ] Integrate sourcing stage into `workflow.py` or `run.py` as optional stage

### Files to Create/Modify
- [ ] Create `scripts/stage7_network_sourcing.py`
- [ ] Modify `scripts/stage3_outreach.py` (add `draft_connection_request()`)
- [ ] Modify `scripts/utils.py` (add Leads DB property mapping)
- [ ] Update `CLAUDE.md` to document new sourcing stage

### Risk Mitigation
- [ ] Implement aggressive rate-limiting for LinkedIn scraping
- [ ] Document ToS compliance strategy
- [ ] Keep manual-send gate non-negotiable in code review
- [ ] Add warnings about experimental/high-risk nature to documentation

### Verification for §3
- [ ] Run new sourcing stage against small batch
- [ ] Confirm leads land in Notion Leads DB as `Identified` only
- [ ] Confirm no message drafted or sent until lead flipped to `Approved`
- [ ] Test manual approval → draft generation flow

---

## Summary by Priority

### High Priority (Blocking reliability)
- AI-call reliability (Section 1): All items
- Company-type classification (Section 2a, 2b, 2c)

### Medium Priority (Quality improvement)
- Sponsorship ambiguity handling (Section 2c)
- Remove false positives (Section 2b)

### Lower Priority (New feature)
- Networking-based sourcing (Section 3): All items (research spike required first)

---

## Commit Strategy

Recommended commits:
1. **Commit 1**: AI reliability (§1) — retry, backoff, exception handling
2. **Commit 2**: Better filtering (§2) — company-type classification, false positive removal, sponsorship handling
3. **Commit 3**: Network sourcing (§3) — new stage, Leads DB, connection request drafting

---

## Documentation Updates

- [ ] Update `CLAUDE.md` with retry/backoff behavior
- [ ] Document new `SPONSORSHIP_MODE` setting
- [ ] Document new sourcing stage and manual approval workflow
- [ ] Add examples to `README.md` for common filtering/sourcing scenarios
