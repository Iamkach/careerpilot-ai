"""
Tests for scripts/provision_notion.py (fork Notion provisioning) and run.py's --init wizard.

Provisioning is create-once and irreversible-ish in a live workspace, so the value here is
pinning the *payloads*: that a fresh tracker is born with every property and all 21 Status
options (defining them at create-time is the whole reason pages.update's option limit doesn't
bite later), that the scratch pad is a single clean URL column and not Notion's template junk,
and that --init writes the returned ids into .env without clobbering the user's other lines.
"""
import pytest

from scripts import provision_notion as pn


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeDatabases:
    def __init__(self, retrieve_schema=None):
        self.created = []
        self._schema = retrieve_schema
        self.fail_unique_id = False

    def create(self, parent, title, properties):
        if self.fail_unique_id and "Job ID" in properties:
            raise RuntimeError("unique_id is not a supported property type")
        name = title[0]["text"]["content"]
        self.created.append({"parent": parent, "title": name, "properties": properties})
        return {"id": f"db-{name.lower().replace(' ', '-')}"}

    def retrieve(self, database_id):
        return self._schema


class FakePages:
    def __init__(self):
        self.created = []

    def create(self, parent, properties):
        self.created.append({"parent": parent, "properties": properties})
        return {"id": "page-careerpilot"}


class FakeNotion:
    def __init__(self, retrieve_schema=None):
        self.pages = FakePages()
        self.databases = FakeDatabases(retrieve_schema)


# A real-shaped Notion id and its normalized (dashed) form, used across the provision tests.
PARENT_RAW = "3a50a7a3e7198071b70bdef6519fb1a5"
PARENT_DASHED = "3a50a7a3-e719-8071-b70b-def6519fb1a5"


def _full_schema(drop_props=(), drop_status=()):
    """A databases.retrieve() response for a fully-provisioned tracker, minus anything dropped."""
    props = {n: spec for n, spec in pn.TRACKER_PROPERTIES.items() if n not in drop_props}
    statuses = [s for s in pn.STATUS_OPTIONS if s not in drop_status]
    props["Status"] = {"select": {"options": [{"name": s} for s in statuses]}}
    return {"properties": props}


# ── provision() ───────────────────────────────────────────────────────────────

def test_provision_creates_page_then_all_three_databases_under_it():
    fake = FakeNotion()
    tracker_id, scratch_id, restricted_id = pn.provision(PARENT_RAW, notion=fake)

    assert len(fake.pages.created) == 1
    # The raw id was normalized to a dashed UUID before hitting the API.
    assert fake.pages.created[0]["parent"]["page_id"] == PARENT_DASHED

    titles = [c["title"] for c in fake.databases.created]
    assert titles == ["Job Search Tracker", "Job Link Scratch Pad", "Restricted Sponsorship Companies"]
    # All DBs are created under the new "Careerpilot-ai" page, not the shared parent.
    assert all(c["parent"]["page_id"] == "page-careerpilot" for c in fake.databases.created)
    assert tracker_id == "db-job-search-tracker"
    assert scratch_id == "db-job-link-scratch-pad"
    assert restricted_id == "db-restricted-sponsorship-companies"


def test_tracker_is_born_with_every_property_and_all_status_options():
    fake = FakeNotion()
    pn.provision(PARENT_RAW, notion=fake)
    props = fake.databases.created[0]["properties"]

    for name in pn.TRACKER_PROPERTIES:
        assert name in props, f"{name} missing from the create payload"

    option_names = {o["name"] for o in props["Status"]["select"]["options"]}
    assert set(pn.STATUS_OPTIONS) <= option_names
    assert len(pn.STATUS_OPTIONS) == 21  # guards against an accidental edit to the vocabulary

    # A Notion database must have exactly one title property.
    assert sum(1 for spec in props.values() if "title" in spec) == 1


def test_scratch_pad_is_a_single_clean_url_column():
    """Not Notion's default Question 1/Question 2/Respondent template — one title column only."""
    fake = FakeNotion()
    pn.provision(PARENT_RAW, notion=fake)
    assert fake.databases.created[1]["properties"] == {"Job URL": {"title": {}}}


def test_restricted_companies_db_is_a_single_clean_name_column():
    fake = FakeNotion()
    pn.provision(PARENT_RAW, notion=fake)
    assert fake.databases.created[2]["properties"] == {"Company": {"title": {}}}


def test_unique_id_rejection_falls_back_without_job_id():
    """A pinned API that rejects the newer unique_id type must not sink the whole provision."""
    fake = FakeNotion()
    fake.databases.fail_unique_id = True
    tracker_id, scratch_id, restricted_id = pn.provision(PARENT_RAW, notion=fake)

    tracker_props = fake.databases.created[0]["properties"]
    assert "Job ID" not in tracker_props
    assert "Status" in tracker_props  # everything else still landed
    assert tracker_id and scratch_id and restricted_id


# ── normalize_page_id() — accept a share link or a raw id ─────────────────────

@pytest.mark.parametrize("raw", [
    PARENT_RAW,                                                       # bare undashed id
    PARENT_DASHED,                                                    # bare dashed id
    f"https://www.notion.so/Careerpilot-ai-{PARENT_RAW}",            # workspace slug URL
    f"https://www.notion.so/me/Careerpilot-ai-{PARENT_RAW}?pvs=4",   # slug URL + query
    f"https://app.notion.com/p/{PARENT_DASHED}?pvs=1",               # /p/<dashed> + query
    f"  https://notion.so/{PARENT_RAW}#frag  ",                       # whitespace + fragment
])
def test_normalize_page_id_extracts_dashed_uuid(raw):
    assert pn.normalize_page_id(raw) == PARENT_DASHED


def test_normalize_page_id_rejects_input_with_no_id():
    with pytest.raises(ValueError):
        pn.normalize_page_id("https://www.notion.so/my-workspace")


# ── validate_schema() ─────────────────────────────────────────────────────────

def test_validate_schema_healthy_db_reports_nothing():
    fake = FakeNotion(retrieve_schema=_full_schema())
    assert pn.validate_schema("db-id", notion=fake) == []


def test_validate_schema_flags_missing_property_and_status():
    fake = FakeNotion(retrieve_schema=_full_schema(drop_props=["Notes"], drop_status=["Applied"]))
    missing = pn.validate_schema("db-id", notion=fake)
    assert "property: Notes" in missing
    assert "status: Applied" in missing


def test_stage7_subset_is_a_slice_of_the_canonical_schema():
    """setup_notion_schema imports these; they must stay a real subset so the paths can't drift."""
    subset = pn._stage7_properties()
    assert set(subset) == set(pn.STAGE7_PROPERTY_NAMES)
    for name, spec in subset.items():
        assert pn.TRACKER_PROPERTIES[name] == spec
    assert set(pn.STAGE7_STATUS_OPTIONS) <= set(pn.STATUS_OPTIONS)


# ── run.py --init wizard: .env upsert ─────────────────────────────────────────

import run  # noqa: E402  (top-level import triggers stdout reconfigure; harmless under pytest)


@pytest.fixture
def cleanup_env():
    keys = ["NOTION_API_KEY", "NOTION_DB_ID", "NOTION_SCRATCH_PAGE_ID", "NOTION_RESTRICTED_COMPANIES_PAGE_ID"]
    import os
    before = {k: os.environ.get(k) for k in keys}
    yield
    for k, v in before.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_upsert_env_replaces_in_place_preserving_other_lines(tmp_path, cleanup_env):
    p = tmp_path / ".env"
    p.write_text("# a comment\nNOTION_API_KEY=old\nAPIFY_API_TOKEN=keepme\n", encoding="utf-8")
    run._upsert_env(p, "NOTION_API_KEY", "new")
    text = p.read_text(encoding="utf-8")

    assert "NOTION_API_KEY=new" in text
    assert "APIFY_API_TOKEN=keepme" in text  # unrelated line untouched
    assert "# a comment" in text             # comments preserved
    assert text.count("NOTION_API_KEY="***REMOVED-SECRET***".env"
    p.write_text("APIFY_API_TOKEN=keepme\n", encoding="utf-8")
    run._upsert_env(p, "NOTION_DB_ID", "abc123")
    assert "NOTION_DB_ID=abc123" in p.read_text(encoding="utf-8")


def test_init_wizard_provisions_and_persists_ids(tmp_path, monkeypatch, cleanup_env):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setenv("NOTION_DB_ID", "")  # simulate an un-provisioned fork
    monkeypatch.setattr(run, "check_setup", lambda: None)

    answers = iter(["tok-123", "parent-xyz"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    monkeypatch.setattr("scripts.provision_notion.provision",
                        lambda parent: ("trk-id", "scr-id", "res-id"))

    assert run.init_wizard() == 0

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "NOTION_API_KEY=tok-123" in env_text
    assert "NOTION_DB_ID=trk-id" in env_text
    assert "NOTION_SCRATCH_PAGE_ID=scr-id" in env_text
    assert "NOTION_RESTRICTED_COMPANIES_PAGE_ID=res-id" in env_text
