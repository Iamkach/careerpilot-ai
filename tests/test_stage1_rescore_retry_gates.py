"""
Regression test for a real production bug found 2026-07-16: rescore_retry_jobs() promoted
every successfully-rescored job straight to 'Scraped', without applying the same
EXCLUDE_NO_SPONSORSHIP / SKIP_COMPANY_TYPES / MIN_ATS_SCORE gates the normal scrape path in
run() applies before writing a job to Notion at all. That let jobs a fresh scrape would have
silently dropped (a JD the AI classified as sponsorship="no", a staffing/consulting agency
posting, a below-threshold ATS score) survive in the tracker as 'Scraped' just because they
happened to fail scoring on their first pass and get recovered through this path instead.

Concretely: an earlier chunking-bug incident queued 104 jobs into 'Retry'; recovering them via
rescore_retry_jobs() let 7 through with Sponsorship="no" or an obvious staffing-agency company
(Job IDs 437, 460, 489, 490, 496, 504, 506 in the live Notion tracker) that should have been
filtered out like any other no-sponsor/staffing job.
"""
import json

from scripts import stage1_scrape


def _score_entry(url, score, sponsorship="unknown", company_type="product", missing=None):
    return {
        "url": url, "score": score, "missing_keywords": missing or [],
        "sponsorship": sponsorship, "company_type": company_type,
    }


def test_rescore_retry_jobs_applies_the_same_post_scoring_gates_as_a_fresh_scrape(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    monkeypatch.setattr(stage1_scrape, "EXCLUDE_NO_SPONSORSHIP", True)
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_TYPES", {"staffing_or_consulting"})
    monkeypatch.setattr(stage1_scrape, "MIN_ATS_SCORE", 30)

    fake_db = patch_notion_db(stage1_scrape)
    good        = fake_db.seed(status="Retry", title="Backend Engineer", company="Acme Corp",
                                url="u-good", description="jd", scoring_attempts=1)
    no_sponsor  = fake_db.seed(status="Retry", title="Front End Engineer", company="Walmart",
                                url="u-no-sponsor", description="jd", scoring_attempts=1)
    staffing    = fake_db.seed(status="Retry", title="Sr. Software Developer", company="Experis",
                                url="u-staffing", description="jd", scoring_attempts=1)
    low_score   = fake_db.seed(status="Retry", title="Some Role", company="Random Co",
                                url="u-low-score", description="jd", scoring_attempts=1)

    canned = [
        _score_entry("u-good", 70),
        _score_entry("u-no-sponsor", 70, sponsorship="no"),
        _score_entry("u-staffing", 70, company_type="staffing_or_consulting"),
        _score_entry("u-low-score", 10),
    ]
    patch_ai_chat(stage1_scrape, response=json.dumps(canned))

    counters = stage1_scrape.rescore_retry_jobs("resume text")

    assert counters == {"recovered": 1, "filtered": 3, "given_up": 0, "still_retrying": 0}

    assert fake_db._pages[good]["status"] == "Scraped"

    for page_id, reason_snippet in (
        (no_sponsor, "no-sponsor"),
        (staffing, "staffing"),
        (low_score, "low-ats-score"),
    ):
        rec = fake_db._pages[page_id]
        assert rec["status"] == "Disregard"
        assert reason_snippet in rec["notes"]


def test_rescore_retry_jobs_recovers_normally_when_nothing_is_gated(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    monkeypatch.setattr(stage1_scrape, "EXCLUDE_NO_SPONSORSHIP", True)
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_TYPES", {"staffing_or_consulting"})
    monkeypatch.setattr(stage1_scrape, "MIN_ATS_SCORE", 30)

    fake_db = patch_notion_db(stage1_scrape)
    page_id = fake_db.seed(status="Retry", title="Backend Engineer", company="Acme Corp",
                            url="u1", description="jd", scoring_attempts=1)
    patch_ai_chat(stage1_scrape, response=json.dumps([_score_entry("u1", 80)]))

    counters = stage1_scrape.rescore_retry_jobs("resume text")

    assert counters["recovered"] == 1
    assert counters["filtered"] == 0
    assert fake_db._pages[page_id]["status"] == "Scraped"
    assert fake_db._pages[page_id]["ats_score"] == 80
