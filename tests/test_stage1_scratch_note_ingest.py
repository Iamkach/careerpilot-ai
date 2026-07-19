"""
Contract tests for scripts/stage1_scrape.py's ingest_from_scratch_note() — the pre-ingest
step that promotes URLs dropped as rows in the Notion scratch-note database (one URL per
row's title property) to minimal Status=Interested rows in the Jobs Tracker DB, so the
existing ingest_interested_from_notion() can enrich/score/promote them unchanged. A row is
archived out of the scratch database once successfully converted (or found to be a
duplicate); a row that fails to convert is left in place for the next run.

No AI call is involved in this feature (dedup/CRUD only), so this belongs in the pytest
contract-test suite rather than scripts/run_evals.py's AI-judgment eval layer.
"""
import json

from scripts import stage1_scrape, utils


class _FakeQuery:
    def __init__(self, pages: list[dict]):
        self._pages = pages

    def query(self, database_id, start_cursor=None):
        return {"results": self._pages, "has_more": False}


class _FakeDatabasesClient:
    """Minimal stand-in for notion_client's `.databases.query` — used to unit-test
    get_scratch_note_entries()'s own title-property extraction (finds the title column by
    type, not by name), which patch_notion_db's FakeNotionDB deliberately does not
    reimplement (it fakes the parsed *output*, not the Notion read internals)."""

    def __init__(self, pages: list[dict]):
        self.databases = _FakeQuery(pages)


def _title_page(page_id: str, url: str, title_prop_name: str = "Question 1") -> dict:
    return {
        "id": page_id,
        "properties": {
            title_prop_name: {"type": "title", "title": [{"plain_text": url}]},
            "Respondent":    {"type": "created_by"},
        },
    }


def test_get_scratch_note_entries_reads_title_property_by_type_not_name(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_SCRATCH_PAGE_ID", "fake-scratch-db")
    monkeypatch.setattr(utils, "_notion", lambda: _FakeDatabasesClient([
        _title_page("row-1", "https://example.com/jobs/1"),
        _title_page("row-2", "https://example.com/jobs/2"),
    ]))

    entries = utils.get_scratch_note_entries()

    assert entries == [
        {"page_id": "row-1", "url": "https://example.com/jobs/1"},
        {"page_id": "row-2", "url": "https://example.com/jobs/2"},
    ]


def test_get_scratch_note_entries_skips_blank_title_rows(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_SCRATCH_PAGE_ID", "fake-scratch-db")
    monkeypatch.setattr(utils, "_notion", lambda: _FakeDatabasesClient([
        _title_page("row-1", "https://example.com/jobs/1"),
        _title_page("row-2", ""),
    ]))

    entries = utils.get_scratch_note_entries()

    assert entries == [{"page_id": "row-1", "url": "https://example.com/jobs/1"}]


def test_scratch_note_creates_interested_row_per_new_url(patch_notion_db):
    fake_db = patch_notion_db(stage1_scrape)
    fake_db.seed_scratch_note(["https://example.com/jobs/1", "https://example.com/jobs/2"])

    added = stage1_scrape.ingest_from_scratch_note()

    assert added == 2
    statuses = {rec["url"]: rec["status"] for rec in fake_db._pages.values()}
    titles = {rec["url"]: rec["title"] for rec in fake_db._pages.values()}
    assert statuses == {
        "https://example.com/jobs/1": "Interested",
        "https://example.com/jobs/2": "Interested",
    }
    assert all(t == "Pending intake" for t in titles.values())
    assert fake_db._scratch_rows == {}


def test_scratch_note_drops_already_tracked_url_without_duplicating(patch_notion_db):
    fake_db = patch_notion_db(stage1_scrape)
    fake_db.seed(status="Scraped", url="https://example.com/jobs/1", title="Already Tracked")
    fake_db.seed_scratch_note(["https://example.com/jobs/1", "https://example.com/jobs/2"])

    added = stage1_scrape.ingest_from_scratch_note()

    assert added == 1
    urls = [rec["url"] for rec in fake_db._pages.values()]
    assert urls.count("https://example.com/jobs/1") == 1
    assert "https://example.com/jobs/2" in urls
    assert fake_db._scratch_rows == {}  # duplicate row archived too, not left to reprocess forever


def test_scratch_note_retains_failed_row_for_retry(patch_notion_db, monkeypatch):
    fake_db = patch_notion_db(stage1_scrape)
    page_ids = fake_db.seed_scratch_note(
        ["https://example.com/jobs/good", "https://example.com/jobs/bad"]
    )
    bad_page_id = page_ids[1]

    real_add = fake_db.db_add_interested_url

    def flaky_add(url):
        if url == "https://example.com/jobs/bad":
            return None
        return real_add(url)

    monkeypatch.setattr(stage1_scrape, "db_add_interested_url", flaky_add)

    added = stage1_scrape.ingest_from_scratch_note()

    assert added == 1
    assert fake_db._scratch_rows == {bad_page_id: "https://example.com/jobs/bad"}


def test_scratch_note_noop_when_unconfigured(patch_notion_db):
    fake_db = patch_notion_db(stage1_scrape)  # _scratch_rows defaults to {}

    added = stage1_scrape.ingest_from_scratch_note()

    assert added == 0
    assert fake_db._pages == {}


def test_scratch_note_wired_before_existing_interested_ingest_in_run(
    patch_notion_db, patch_ai_chat, monkeypatch,
):
    fake_db = patch_notion_db(stage1_scrape)
    fake_db.seed_scratch_note(["https://example.com/jobs/new"])

    # The seeded URL is non-LinkedIn, so ingest_interested_from_notion() enriches it via the
    # per-URL enrich_job_url() path (not the batch scrape_job_urls()); mock that so no real
    # HTTP fetch happens. Both are stubbed to keep the test robust to either routing.
    _enriched = {
        "title": "Backend Engineer", "company": "Acme Corp",
        "location": "Remote - US", "description": "jd",
    }
    monkeypatch.setattr(stage1_scrape, "enrich_job_url", lambda url: dict(_enriched))
    monkeypatch.setattr(stage1_scrape, "scrape_job_urls",
                        lambda urls: {u: dict(_enriched) for u in urls})
    canned = [{
        "url": "https://example.com/jobs/new", "score": 80, "missing_keywords": [],
        "sponsorship": "unknown", "company_type": "product",
    }]
    patch_ai_chat(stage1_scrape, response=json.dumps(canned))

    monkeypatch.setattr(stage1_scrape, "TARGET_ROLES", [])
    monkeypatch.setattr(stage1_scrape, "ENABLED_SOURCES", [])
    monkeypatch.setattr(stage1_scrape, "load_resume", lambda: "resume text")

    stage1_scrape.run()

    rec = next(r for r in fake_db._pages.values() if r["url"] == "https://example.com/jobs/new")
    assert rec["status"] == "Scraped"
    assert fake_db._scratch_rows == {}
