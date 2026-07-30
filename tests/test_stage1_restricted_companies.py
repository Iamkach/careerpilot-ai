"""
Step 12 — Notion-managed restricted-sponsorship company list.

Covers scripts/utils.py's get_restricted_companies_from_notion() (raw Notion read, mirrors
the title-property-by-type pattern in tests/test_stage1_scratch_note_ingest.py) and
get_restricted_sponsorship_companies() (merge with the RESTRICTED_SPONSORSHIP_COMPANIES
fallback), plus scripts/stage1_scrape.py's is_restricted_sponsorship_company() and the new
_pre_filter() branch that uses it.
"""
import io

from scripts import stage1_scrape, utils


class _FakeQuery:
    def __init__(self, pages: list[dict]):
        self._pages = pages

    def query(self, database_id, start_cursor=None):
        return {"results": self._pages, "has_more": False}


class _FakeDatabasesClient:
    def __init__(self, pages: list[dict]):
        self.databases = _FakeQuery(pages)


class _RaisingDatabasesClient:
    class _Databases:
        def query(self, **kwargs):
            raise RuntimeError("boom")

    def __init__(self):
        self.databases = self._Databases()


def _name_page(page_id: str, name: str, title_prop_name: str = "Name") -> dict:
    return {
        "id": page_id,
        "properties": {
            title_prop_name: {"type": "title", "title": [{"plain_text": name}]},
        },
    }


def test_unconfigured_returns_empty(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_RESTRICTED_COMPANIES_PAGE_ID", "")
    assert utils.get_restricted_companies_from_notion() == []


def test_reads_company_names_by_title_property_type(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_RESTRICTED_COMPANIES_PAGE_ID", "fake-restricted-db")
    monkeypatch.setattr(utils, "_notion", lambda: _FakeDatabasesClient([
        _name_page("row-1", "Restricted Co"), _name_page("row-2", "Another Co"),
    ]))

    assert utils.get_restricted_companies_from_notion() == ["Restricted Co", "Another Co"]


def test_skips_blank_title_rows(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_RESTRICTED_COMPANIES_PAGE_ID", "fake-restricted-db")
    monkeypatch.setattr(utils, "_notion", lambda: _FakeDatabasesClient([
        _name_page("row-1", "Restricted Co"), _name_page("row-2", ""),
    ]))

    assert utils.get_restricted_companies_from_notion() == ["Restricted Co"]


def test_read_failure_returns_empty_not_raises(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_RESTRICTED_COMPANIES_PAGE_ID", "fake-restricted-db")
    monkeypatch.setattr(utils, "_notion", lambda: _RaisingDatabasesClient())

    assert utils.get_restricted_companies_from_notion() == []


def test_merges_hardcoded_fallback_with_notion_list(monkeypatch):
    monkeypatch.setattr(utils, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Hardcoded Co"])
    monkeypatch.setattr(utils, "get_restricted_companies_from_notion", lambda: ["Notion Co"])

    assert utils.get_restricted_sponsorship_companies() == ["Hardcoded Co", "Notion Co"]


def test_is_restricted_sponsorship_company_word_boundary_match():
    restricted = ["Restricted Co"]
    assert stage1_scrape.is_restricted_sponsorship_company("Restricted Co", restricted)
    assert stage1_scrape.is_restricted_sponsorship_company("Restricted Co Inc.", restricted)
    assert not stage1_scrape.is_restricted_sponsorship_company("Acme Corp", restricted)
    assert not stage1_scrape.is_restricted_sponsorship_company("", restricted)


def test_pre_filter_drops_restricted_sponsorship_company(monkeypatch):
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANIES", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_KEYWORDS", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_TITLE_KEYWORDS", [])
    job = {
        "url": "https://example.com/jobs/1", "title": "Backend Engineer",
        "company": "Restricted Co", "location": "Remote", "description": "",
        "posted_date": None,
    }
    counters = {
        "stale": 0, "company": 0, "restricted-sponsorship": 0, "title": 0,
        "location": 0, "sponsorship": 0, "applicants": 0, "duplicate": 0,
    }

    kept = stage1_scrape._pre_filter(
        job, seen_urls=set(), existing_urls=set(), existing_fps=set(),
        counters=counters, drop_fh=io.StringIO(), restricted=["Restricted Co"],
    )

    assert kept is False
    assert counters["restricted-sponsorship"] == 1
    assert counters["company"] == 0


def test_pre_filter_keeps_unrestricted_company(monkeypatch):
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANIES", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_COMPANY_KEYWORDS", [])
    monkeypatch.setattr(stage1_scrape, "SKIP_TITLE_KEYWORDS", [])
    monkeypatch.setattr(stage1_scrape, "EXCLUDE_NO_SPONSORSHIP", False)
    monkeypatch.setattr(stage1_scrape, "MAX_APPLICANT_COUNT", 0)
    job = {
        "url": "https://example.com/jobs/1", "title": "Backend Engineer",
        "company": "Acme Corp", "location": "Remote", "description": "",
        "posted_date": None,
    }
    counters = {
        "stale": 0, "company": 0, "restricted-sponsorship": 0, "title": 0,
        "location": 0, "sponsorship": 0, "applicants": 0, "duplicate": 0,
    }

    kept = stage1_scrape._pre_filter(
        job, seen_urls=set(), existing_urls=set(), existing_fps=set(),
        counters=counters, drop_fh=io.StringIO(), restricted=["Restricted Co"],
    )

    assert kept is True
    assert counters["restricted-sponsorship"] == 0
