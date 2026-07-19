"""
Tests for the Stage 1 auto-review gate (feature/god-speed): a scored job whose JD the AI
reads as explicitly sponsorship-friendly ("yes") and scoring at/above AUTO_REVIEW_MIN_SCORE
skips the manual Scraped→Reviewed gate and lands in 'Reviewed' directly; everything less
certain (silent/"unknown" sponsorship, or a lower score) still lands in 'Scraped' for a human
second-eye pass.

The gate decision lives in one helper, stage1_scrape._auto_review_status(), applied at all
three places a job would otherwise land in 'Scraped': the fresh scrape write, the "Interested"
intake promotion, and the Retry-recovery promotion. These tests cover the helper's truth table
plus two of the three call sites (Interested intake and Retry recovery) end-to-end against the
fake Notion DB; the fresh-scrape site shares the exact same helper call.
"""
import json

import pytest

from scripts import stage1_scrape


def _score_entry(url, score, sponsorship="unknown", company_type="product", missing=None):
    return {
        "url": url, "score": score, "missing_keywords": missing or [],
        "sponsorship": sponsorship, "company_type": company_type,
    }


# ── 1. Helper truth table ────────────────────────────────────────────────────

@pytest.mark.parametrize("sponsorship, score, expected", [
    ("yes",     80,   "Reviewed"),   # explicit sponsorship + comfortably above threshold
    ("yes",     35,   "Reviewed"),   # exactly at the threshold (>=)
    ("yes",     34,   "Scraped"),    # explicit sponsorship but below threshold
    ("unknown", 90,   "Scraped"),    # silent JD never auto-promotes, however high the score
    ("no",      95,   "Scraped"),    # (defensive) "no" never auto-promotes; it's dropped upstream
    ("yes",     None, "Scraped"),    # missing score (e.g. give-up path) never auto-promotes
])
def test_auto_review_status_truth_table(monkeypatch, sponsorship, score, expected):
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)
    assert stage1_scrape._auto_review_status(sponsorship, score) == expected


# ── 2. Retry-recovery call site ──────────────────────────────────────────────

def test_rescore_retry_promotes_confident_sponsor_job_to_reviewed(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    """A Retry job the AI recovers as sponsorship='yes' and score >= AUTO_REVIEW_MIN_SCORE
    lands in 'Reviewed', not 'Scraped' — skipping the human gate on the recovery path too."""
    monkeypatch.setattr(stage1_scrape, "EXCLUDE_NO_SPONSORSHIP", True)
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_TYPES", {"staffing_or_consulting"})
    monkeypatch.setattr(stage1_scrape, "MIN_ATS_SCORE", 30)
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)

    fake_db = patch_notion_db(stage1_scrape)
    sponsor_hi = fake_db.seed(status="Retry", title="Backend Engineer", company="Acme Corp",
                              url="u-sponsor-hi", description="jd", scoring_attempts=1)
    silent_hi  = fake_db.seed(status="Retry", title="Platform Engineer", company="Beta Inc",
                              url="u-silent-hi", description="jd", scoring_attempts=1)

    canned = [
        _score_entry("u-sponsor-hi", 70, sponsorship="yes"),
        _score_entry("u-silent-hi", 90, sponsorship="unknown"),
    ]
    patch_ai_chat(stage1_scrape, response=json.dumps(canned))

    counters = stage1_scrape.rescore_retry_jobs("resume text")

    assert counters == {"recovered": 2, "filtered": 0, "given_up": 0, "still_retrying": 0}
    assert fake_db._pages[sponsor_hi]["status"] == "Reviewed"   # auto-promoted
    assert fake_db._pages[silent_hi]["status"] == "Scraped"     # human gate


def test_rescore_retry_does_not_promote_confident_sponsor_below_threshold(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    """sponsorship='yes' but score below AUTO_REVIEW_MIN_SCORE (yet at/above MIN_ATS_SCORE, so
    still recovered) stays in 'Scraped', not 'Reviewed'."""
    monkeypatch.setattr(stage1_scrape, "EXCLUDE_NO_SPONSORSHIP", True)
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_TYPES", {"staffing_or_consulting"})
    monkeypatch.setattr(stage1_scrape, "MIN_ATS_SCORE", 30)
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)

    fake_db = patch_notion_db(stage1_scrape)
    page_id = fake_db.seed(status="Retry", title="Backend Engineer", company="Acme Corp",
                           url="u1", description="jd", scoring_attempts=1)
    patch_ai_chat(stage1_scrape, response=json.dumps([_score_entry("u1", 32, sponsorship="yes")]))

    counters = stage1_scrape.rescore_retry_jobs("resume text")

    assert counters["recovered"] == 1
    assert fake_db._pages[page_id]["status"] == "Scraped"


# ── 3. "Interested" intake call site ─────────────────────────────────────────

def test_ingest_interested_promotes_confident_sponsor_job_to_reviewed(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    """A hand-added 'Interested' job enriched to sponsorship='yes' with score >=
    AUTO_REVIEW_MIN_SCORE is promoted straight to 'Reviewed'; a silent one lands in 'Scraped'.
    Uses linkedin.com URLs so enrichment goes through the mocked batch scrape_job_urls()
    rather than the per-URL enrich_job_url() HTTP path."""
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)

    fake_db = patch_notion_db(stage1_scrape)
    sponsor_url = "https://www.linkedin.com/jobs/view/sponsor"
    silent_url  = "https://www.linkedin.com/jobs/view/silent"
    sponsor_pg = fake_db.seed(status="Interested", title="Pending", company="Acme",
                              location="Remote - US", url=sponsor_url)
    silent_pg  = fake_db.seed(status="Interested", title="Pending", company="Beta",
                              location="Remote - US", url=silent_url)

    monkeypatch.setattr(stage1_scrape, "scrape_job_urls", lambda urls: {
        sponsor_url: {"title": "Backend Engineer", "company": "Acme Corp",
                      "location": "Remote - US", "description": "jd sponsor"},
        silent_url:  {"title": "Platform Engineer", "company": "Beta Inc",
                      "location": "Remote - US", "description": "jd silent"},
    })

    canned = [
        _score_entry(sponsor_url, 80, sponsorship="yes"),
        _score_entry(silent_url, 88, sponsorship="unknown"),
    ]
    patch_ai_chat(stage1_scrape, response=json.dumps(canned))

    ingested = stage1_scrape.ingest_interested_from_notion("resume text")

    assert ingested == 2
    assert fake_db._pages[sponsor_pg]["status"] == "Reviewed"   # auto-promoted
    assert fake_db._pages[silent_pg]["status"] == "Scraped"     # human gate
