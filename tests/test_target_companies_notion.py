"""
Step 14 — Notion-managed curated target-companies list + persistent ATS-token store.

Covers scripts/utils.py's get_target_companies_from_notion() (raw Notion read, mirrors the
title-property-by-type pattern in tests/test_stage1_restricted_companies.py),
get_ats_tokens_from_notion() (read into discover_tokens()'s {company: {greenhouse, lever,
ashby, checked}} shape), and upsert_ats_token_to_notion() (create-or-update by title match),
plus scripts/sources.py's discover_tokens() wiring: seeding in Notion target companies,
overlaying Notion's tokens onto the local cache (Notion wins on conflict), and writing a fresh
probe result for a Notion-seeded company back to Notion.
"""
import datetime

from scripts import sources, utils


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.filters_seen = []

    def query(self, database_id, start_cursor=None, filter=None):
        self.filters_seen.append(filter)
        if filter is not None:
            # Simulate a title-equals filter for the upsert lookup path.
            wanted = filter["title"]["equals"]
            matches = [p for p in self._pages if _title_text(p) == wanted]
            return {"results": matches, "has_more": False}
        return {"results": self._pages, "has_more": False}


class _FakePages:
    def __init__(self):
        self.updated = []
        self.created = []

    def update(self, page_id, properties):
        self.updated.append({"page_id": page_id, "properties": properties})

    def create(self, parent, properties):
        self.created.append({"parent": parent, "properties": properties})
        return {"id": "new-page"}


class _FakeNotionClient:
    def __init__(self, pages: list[dict]):
        self.databases = _FakeQuery(pages)
        self.pages = _FakePages()


class _RaisingClient:
    class _Databases:
        def query(self, **kwargs):
            raise RuntimeError("boom")

    def __init__(self):
        self.databases = self._Databases()


def _title_text(page: dict) -> str:
    for prop in page["properties"].values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return ""


def _company_page(page_id: str, company: str, gh: str = "", lv: str = "", ab: str = "",
                   checked: str | None = None) -> dict:
    return {
        "id": page_id,
        "properties": {
            "Company": {"type": "title", "title": [{"plain_text": company}]},
            "Greenhouse": {"type": "rich_text", "rich_text": [{"plain_text": gh}] if gh else []},
            "Lever": {"type": "rich_text", "rich_text": [{"plain_text": lv}] if lv else []},
            "Ashby": {"type": "rich_text", "rich_text": [{"plain_text": ab}] if ab else []},
            "Last Checked": {"type": "date", "date": {"start": checked} if checked else None},
        },
    }


# ── get_target_companies_from_notion() ───────────────────────────────────────

def test_get_target_companies_unconfigured_returns_empty(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "")
    assert utils.get_target_companies_from_notion() == []


def test_get_target_companies_reads_names_by_title_property_type(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    monkeypatch.setattr(utils, "_notion", lambda: _FakeNotionClient([
        _company_page("row-1", "Stripe"), _company_page("row-2", "Notion"),
    ]))
    assert utils.get_target_companies_from_notion() == ["Stripe", "Notion"]


def test_get_target_companies_read_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    monkeypatch.setattr(utils, "_notion", lambda: _RaisingClient())
    assert utils.get_target_companies_from_notion() == []


# ── get_ats_tokens_from_notion() ──────────────────────────────────────────────

def test_get_ats_tokens_unconfigured_returns_empty(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "")
    assert utils.get_ats_tokens_from_notion() == {}


def test_get_ats_tokens_reads_into_expected_shape(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    monkeypatch.setattr(utils, "_notion", lambda: _FakeNotionClient([
        _company_page("row-1", "Stripe", gh="stripe", checked="2026-07-01"),
        _company_page("row-2", "Notion"),  # no tokens found yet
    ]))
    tokens = utils.get_ats_tokens_from_notion()
    assert tokens["Stripe"] == {
        "greenhouse": "stripe", "lever": None, "ashby": None, "checked": "2026-07-01",
    }
    assert tokens["Notion"] == {
        "greenhouse": None, "lever": None, "ashby": None, "checked": None,
    }


def test_get_ats_tokens_read_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    monkeypatch.setattr(utils, "_notion", lambda: _RaisingClient())
    assert utils.get_ats_tokens_from_notion() == {}


# ── upsert_ats_token_to_notion() ──────────────────────────────────────────────

def test_upsert_no_ops_when_unconfigured(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "")
    calls = []
    monkeypatch.setattr(utils, "_notion", lambda: calls.append("called"))
    utils.upsert_ats_token_to_notion("Stripe", "stripe", None, None, "2026-07-30")
    assert calls == []


def test_upsert_updates_existing_row_by_title_match(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    fake = _FakeNotionClient([_company_page("row-1", "Stripe")])
    monkeypatch.setattr(utils, "_notion", lambda: fake)

    utils.upsert_ats_token_to_notion("Stripe", "stripe", None, None, "2026-07-30")

    assert fake.pages.created == []
    assert len(fake.pages.updated) == 1
    update = fake.pages.updated[0]
    assert update["page_id"] == "row-1"
    assert update["properties"]["Greenhouse"]["rich_text"][0]["text"]["content"] == "stripe"
    assert update["properties"]["Last Checked"]["date"]["start"] == "2026-07-30"


def test_upsert_creates_row_when_no_match(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    fake = _FakeNotionClient([])
    monkeypatch.setattr(utils, "_notion", lambda: fake)

    utils.upsert_ats_token_to_notion("Figma", None, None, None, "2026-07-30")

    assert fake.pages.updated == []
    assert len(fake.pages.created) == 1
    created = fake.pages.created[0]
    assert created["parent"] == {"database_id": "fake-target-db"}
    assert created["properties"]["Company"]["title"][0]["text"]["content"] == "Figma"


def test_upsert_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "fake-target-db")
    monkeypatch.setattr(utils, "_notion", lambda: _RaisingClient())
    utils.upsert_ats_token_to_notion("Stripe", "stripe", None, None, "2026-07-30")  # must not raise


# ── discover_tokens() Notion wiring (scripts/sources.py) ─────────────────────

def test_discover_tokens_seeds_in_notion_target_companies(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", False)
    monkeypatch.setattr(sources, "get_target_companies_from_notion", lambda: ["Notion Seed Co"])
    monkeypatch.setattr(sources, "get_ats_tokens_from_notion", lambda: {})

    seen = []

    def spy(company, slug):
        seen.append(company)
        return None

    monkeypatch.setattr(sources, "_probe_greenhouse", spy)
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    tokens = sources.discover_tokens(["Passed Co"], max_new_probes=5)

    assert seen == ["Passed Co", "Notion Seed Co"]
    assert set(tokens) == {"Passed Co", "Notion Seed Co"}


def test_discover_tokens_notion_cache_wins_over_local_cache(monkeypatch, tmp_path):
    """A local ats_tokens.json entry for a Notion-seeded company is overridden by the Notion
    row (Notion is the source of truth for its own rows) — and, since the merged entry already
    has a hit, no re-probe happens."""
    tokens_path = tmp_path / "ats_tokens.json"
    tokens_path.write_text(
        '{"Stripe": {"greenhouse": null, "lever": null, "ashby": null, "checked": "2020-01-01"}}'
    )
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tokens_path)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sources, "get_target_companies_from_notion", lambda: ["Stripe"])
    monkeypatch.setattr(sources, "get_ats_tokens_from_notion", lambda: {
        "Stripe": {"greenhouse": "stripe", "lever": None, "ashby": None, "checked": "2026-07-01"},
    })

    probed = []
    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: probed.append(c) or "wrong")
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    tokens = sources.discover_tokens(["Stripe"], max_new_probes=5)

    assert probed == []  # already has a hit via Notion — no re-probe
    assert tokens["Stripe"]["greenhouse"] == "stripe"


def test_discover_tokens_writes_fresh_result_back_to_notion_for_seeded_company(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", False)
    monkeypatch.setattr(sources, "get_target_companies_from_notion", lambda: ["Stripe"])
    monkeypatch.setattr(sources, "get_ats_tokens_from_notion", lambda: {})
    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: "stripe")
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    upsert_calls = []
    monkeypatch.setattr(
        sources, "upsert_ats_token_to_notion",
        lambda company, gh, lv, ab, checked: upsert_calls.append((company, gh, lv, ab)),
    )

    sources.discover_tokens(["Stripe"], max_new_probes=5)

    assert upsert_calls == [("Stripe", "stripe", None, None)]


def test_discover_tokens_does_not_write_back_for_non_notion_company(monkeypatch, tmp_path):
    """A company that only came from the passed-in `companies` list (not the Notion target
    list) must not get an upsert call — Notion only tracks the rows it actually has."""
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", False)
    monkeypatch.setattr(sources, "get_target_companies_from_notion", lambda: [])
    monkeypatch.setattr(sources, "get_ats_tokens_from_notion", lambda: {})
    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: "acme")
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    upsert_calls = []
    monkeypatch.setattr(
        sources, "upsert_ats_token_to_notion",
        lambda *a, **k: upsert_calls.append(a),
    )

    sources.discover_tokens(["Acme Inc"], max_new_probes=5)

    assert upsert_calls == []


def test_discover_tokens_no_op_when_notion_unset(monkeypatch, tmp_path):
    """Byte-for-byte today's behavior when NOTION_TARGET_COMPANIES_PAGE_ID is unset: both Notion
    helpers return empty and the loop runs exactly as before this feature existed."""
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", False)
    monkeypatch.setattr(utils, "NOTION_TARGET_COMPANIES_PAGE_ID", "")
    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    tokens = sources.discover_tokens(["Acme Inc"], max_new_probes=5)

    assert set(tokens) == {"Acme Inc"}
