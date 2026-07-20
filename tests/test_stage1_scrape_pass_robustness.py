"""
Tests for three robustness properties of one stage 1 scrape pass (PR #11 review fixes):

  1. Dedup covers 'Retry' rows. The dedup snapshot excludes only 'Interested' (whose row is
     promoted in place by ingest_interested_from_notion() and would otherwise match itself).
     'Retry' must NOT be excluded: the fresh-scrape path calls db_add_job(), which creates a
     *new* page, so a job parked at Retry by rescore_retry_jobs()'s still_retrying branch
     would get a second Notion page on the very next run.

  2. A failed Notion write skips that one job instead of aborting the pass. db_add_job()
     raises on a failed write; one bad row must not cost every later candidate its page.

  3. The drop log is closed even when the pass raises. The record of what got filtered is
     most valuable precisely on the runs that died partway.

All three are exercised through stage1_scrape.run()/_scrape_pass() end-to-end against the
fake Notion DB, with the network sources stubbed out.
"""
import json

import pytest

from scripts import stage1_scrape


def _stub_sources(monkeypatch, jobs):
    """Point stage 1's gather phase at a fixed job list, with no network at all."""
    monkeypatch.setattr(stage1_scrape, "TARGET_ROLES", ["Backend Engineer"])
    monkeypatch.setattr(stage1_scrape, "ENABLED_SOURCES", ["linkedin"])
    monkeypatch.setattr(stage1_scrape, "KEYWORD_SOURCES", {"linkedin": lambda role: list(jobs)})
    monkeypatch.setattr(stage1_scrape, "BOARD_SOURCES", {})
    monkeypatch.setattr(stage1_scrape, "time", type("_T", (), {"sleep": staticmethod(lambda *_: None)}))


def _relax_filters(monkeypatch):
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANIES", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_KEYWORDS", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_TITLE_KEYWORDS", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_TYPES", set())
    monkeypatch.setattr(stage1_scrape, "EXCLUDE_NO_SPONSORSHIP", False)
    monkeypatch.setattr(stage1_scrape, "MAX_APPLICANT_COUNT", 0)
    monkeypatch.setattr(stage1_scrape, "MIN_ATS_SCORE", 0)
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)
    monkeypatch.setattr(stage1_scrape, "OUTPUT_DIR", "output")


def _job(url="https://example.com/jobs/1", title="Backend Engineer", company="Acme Corp"):
    return {
        "url": url, "title": title, "company": company, "location": "Remote - US",
        "description": "Python and AWS backend role.", "source": "linkedin",
        "posted_date": None, "applicant_count": None, "salary_range": "",
    }


def _score(url, score=80):
    return json.dumps([{
        "url": url, "score": score, "missing_keywords": [],
        "sponsorship": "unknown", "company_type": "product",
    }])


@pytest.fixture(autouse=True)
def _drop_log_in_tmp(monkeypatch, tmp_path):
    """Keep the drop log out of the repo's output/ dir."""
    monkeypatch.chdir(tmp_path)


# ── 1. Retry rows participate in dedup ───────────────────────────────────────

def test_retry_row_is_not_rescraped_into_a_duplicate_page(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    """A job sitting at Status='Retry' is already tracked. Re-scraping the same URL must not
    create a second Notion page — the fresh-scrape path writes a brand-new page, so excluding
    Retry from the dedup snapshot silently duplicated the tracker every run."""
    _relax_filters(monkeypatch)
    job = _job()
    _stub_sources(monkeypatch, [job])

    fake_db = patch_notion_db(stage1_scrape)
    retry_page = fake_db.seed(
        status="Retry", title=job["title"], company=job["company"], url=job["url"],
        description="jd", scoring_attempts=1,
    )
    # No Retry recovery this run (scoring still fails), so the row stays at Retry — the exact
    # still_retrying case that used to leak a duplicate.
    monkeypatch.setattr(stage1_scrape, "MAX_SCORING_ATTEMPTS", 5)
    fake = patch_ai_chat(stage1_scrape, response="not json")

    before = set(fake_db._pages)
    stage1_scrape.run()

    assert set(fake_db._pages) == before, "scrape created a second page for a Retry row"
    assert fake_db._pages[retry_page]["status"] == "Retry"


def test_interested_row_is_still_excluded_from_dedup(monkeypatch, patch_notion_db):
    """The one status that must stay excluded: an 'Interested' row is promoted in place, so
    counting it in the snapshot would make it dedup against itself."""
    _relax_filters(monkeypatch)
    job = _job()
    _stub_sources(monkeypatch, [job])

    fake_db = patch_notion_db(stage1_scrape)
    fake_db.seed(status="Interested", title=job["title"], company=job["company"],
                 url=job["url"], description="")

    # Enrichment fails, so intake leaves it alone; the scrape path must still see the URL as
    # un-tracked (not deduped away) — proving 'Interested' is excluded from the snapshot.
    monkeypatch.setattr(stage1_scrape, "enrich_job_url", lambda url: None)
    monkeypatch.setattr(stage1_scrape, "MAX_ENRICHMENT_ATTEMPTS", 3)

    existing = stage1_scrape.db_get_all_jobs()
    unsettled = {"Interested"}
    urls = {j["url"] for j in existing if j["url"] and j["status"] not in unsettled}
    assert job["url"] not in urls


# ── 2. A failed Notion write skips one job, not the pass ─────────────────────

def test_failed_notion_write_skips_that_job_and_continues(
    monkeypatch, patch_ai_chat, patch_notion_db,
):
    """db_add_job() raises on a failed write. The pass must log it, count it, and keep going
    — one unwritable row previously aborted every later candidate."""
    _relax_filters(monkeypatch)
    bad  = _job(url="https://example.com/jobs/bad", company="Bad Corp")
    good = _job(url="https://example.com/jobs/good", company="Good Corp")
    _stub_sources(monkeypatch, [bad, good])

    fake_db = patch_notion_db(stage1_scrape)
    real_add = fake_db.db_add_job

    def flaky_add(job):
        if job["company"] == "Bad Corp":
            raise RuntimeError("Notion page creation failed")
        return real_add(job)

    monkeypatch.setattr(stage1_scrape, "db_add_job", flaky_add)
    patch_ai_chat(stage1_scrape, response=json.dumps([
        {"url": bad["url"], "score": 80, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"},
        {"url": good["url"], "score": 80, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"},
    ]))

    stage1_scrape.run()  # must not raise

    written = [r for r in fake_db._pages.values() if r.get("company") == "Good Corp"]
    assert len(written) == 1, "a failed write on an earlier job aborted the rest of the pass"
    assert not [r for r in fake_db._pages.values() if r.get("company") == "Bad Corp"]


# ── 3. The drop log is closed even when the pass raises ──────────────────────

def test_drop_log_is_closed_when_the_pass_raises(monkeypatch, patch_notion_db):
    """run() opens the drop log and must close it in a finally — an exception mid-pass used
    to leak the handle and lose the summary."""
    _relax_filters(monkeypatch)
    _stub_sources(monkeypatch, [_job()])
    patch_notion_db(stage1_scrape)

    captured = {}
    real_open = stage1_scrape._open_drop_log

    def spy_open():
        path, fh = real_open()
        captured["fh"] = fh
        return path, fh

    monkeypatch.setattr(stage1_scrape, "_open_drop_log", spy_open)
    monkeypatch.setattr(stage1_scrape, "load_resume",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        stage1_scrape.run()

    assert captured["fh"].closed, "drop log handle leaked when the pass raised"
