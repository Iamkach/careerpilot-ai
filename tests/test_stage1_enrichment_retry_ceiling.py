"""
Closes the "residual gap" #3 flagged in docs/refinement-plans/sourcing/
career-site-enrichment-fallback.md: before this, a hand-added "Interested" job whose URL
enrichment kept failing (e.g. a JS-rendered career page generic_url_fetch() can't extract
text from) was retried identically on every --ingest run forever, with no ceiling.

ingest_interested_from_notion() now mirrors rescore_retry_jobs()'s MAX_SCORING_ATTEMPTS
pattern via MAX_ENRICHMENT_ATTEMPTS: an "Interested" row whose enrichment fails gets an
incrementing "Enrichment Attempts" counter and stays "Interested" while under the ceiling;
once attempts exceed it, the row is promoted to "Scraped" with a Notes marker asking the
human to add the JD by hand, instead of looping forever.
"""
from scripts import stage1_scrape


def test_ingest_interested_still_retries_enrichment_failure_under_the_ceiling(
    monkeypatch, patch_notion_db,
):
    monkeypatch.setattr(stage1_scrape, "MAX_ENRICHMENT_ATTEMPTS", 3)
    fake_db = patch_notion_db(stage1_scrape)
    url = "https://careers.example.com/spa-shell-job"
    page_id = fake_db.seed(status="Interested", title="Pending intake", company="",
                            location="", url=url, enrichment_attempts=1)

    # Simulate a JS-rendered career page that never yields real JD text.
    monkeypatch.setattr(stage1_scrape, "enrich_job_url", lambda u: None)

    ingested = stage1_scrape.ingest_interested_from_notion("resume text")

    assert ingested == 0
    rec = fake_db._pages[page_id]
    assert rec["status"] == "Interested"
    assert rec["enrichment_attempts"] == 2


def test_ingest_interested_gives_up_once_enrichment_attempts_exceed_the_ceiling(
    monkeypatch, patch_notion_db,
):
    monkeypatch.setattr(stage1_scrape, "MAX_ENRICHMENT_ATTEMPTS", 3)
    fake_db = patch_notion_db(stage1_scrape)
    url = "https://careers.example.com/spa-shell-job"
    page_id = fake_db.seed(status="Interested", title="Pending intake", company="",
                            location="", url=url, enrichment_attempts=3)

    monkeypatch.setattr(stage1_scrape, "enrich_job_url", lambda u: None)

    ingested = stage1_scrape.ingest_interested_from_notion("resume text")

    assert ingested == 0
    rec = fake_db._pages[page_id]
    assert rec["status"] == "Scraped"
    assert rec["enrichment_attempts"] == 4
    assert "enrichment failed" in rec["notes"]


def test_ingest_interested_resets_nothing_on_successful_enrichment(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    """A job that enriches successfully is scored/promoted as usual — the ceiling logic
    must only fire on the failure branch, never touch a job that enriched fine."""
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)
    fake_db = patch_notion_db(stage1_scrape)
    url = "https://careers.example.com/real-job"
    page_id = fake_db.seed(status="Interested", title="Pending intake", company="",
                            location="", url=url, enrichment_attempts=2)

    monkeypatch.setattr(stage1_scrape, "enrich_job_url", lambda u: {
        "title": "Backend Engineer", "company": "Acme Corp",
        "location": "Remote - US", "description": "a real JD",
    })
    patch_ai_chat(stage1_scrape, response=(
        '[{"url": "%s", "score": 80, "missing_keywords": [], '
        '"sponsorship": "unknown", "company_type": "product"}]' % url
    ))

    ingested = stage1_scrape.ingest_interested_from_notion("resume text")

    assert ingested == 1
    assert fake_db._pages[page_id]["status"] == "Reviewed"
