"""
Tests for scripts/setup_notion_schema.py — the one-time Stage 7 schema migration.

The dangerous operation here is patching the Status select: Notion replaces the option list
wholesale, so sending only the new options would delete every existing status and take the
pipeline's entire vocabulary (Scraped, Reviewed, Applied, Retry...) with it. Most of this file
exists to pin that.
"""
import pytest

from scripts import setup_notion_schema as sns
from scripts.setup_notion_schema import (
    missing_status_options, missing_properties, build_patch, REQUIRED_STATUS_OPTIONS,
)

EXISTING_STATUSES = [
    "Interested", "Scraped", "Reviewed", "Resume Tailored", "Applied", "Outreach Sent",
    "Interview Scheduled", "Offer Received", "Retry", "Disregard", "Blacklist", "Archived",
    "Rejected", "Human Review",
]


def _schema(statuses=None, props=None):
    """A Notion databases.retrieve() response shaped like the real tracker."""
    properties = {
        "Job Title": {"title": {}},
        "Company": {"rich_text": {}},
        "Status": {"select": {"options": [
            {"id": f"id-{i}", "name": n, "color": "default"}
            for i, n in enumerate(EXISTING_STATUSES if statuses is None else statuses)
        ]}},
    }
    properties.update(props or {})
    return {"title": [{"plain_text": "Job Search Tracker"}], "properties": properties}


# ── Detection ─────────────────────────────────────────────────────────────────

def test_all_stage7_statuses_detected_as_missing_on_a_fresh_db():
    assert missing_status_options(_schema()) == REQUIRED_STATUS_OPTIONS


def test_already_present_statuses_are_not_re_added():
    schema = _schema(statuses=EXISTING_STATUSES + ["Application Queued", "Apply Failed"])
    missing = missing_status_options(schema)
    assert "Application Queued" not in missing
    assert "Apply Failed" not in missing
    assert "Needs Human: Captcha" in missing


def test_fully_migrated_db_reports_nothing_missing():
    schema = _schema(
        statuses=EXISTING_STATUSES + REQUIRED_STATUS_OPTIONS,
        props={"Apply Channel": {"select": {}}, "Apply Attempts": {"number": {}},
               "Needs Human Reason": {"rich_text": {}}, "Application Log": {"rich_text": {}}},
    )
    assert missing_status_options(schema) == []
    assert missing_properties(schema) == []
    assert build_patch(schema) == {}


def test_missing_properties_detected():
    assert set(missing_properties(_schema())) == {
        "Apply Channel", "Apply Attempts", "Needs Human Reason", "Application Log"}


def test_missing_status_property_entirely_is_handled():
    """A DB with no Status property at all must not crash the detector."""
    schema = {"properties": {"Job Title": {"title": {}}}}
    assert missing_status_options(schema) == REQUIRED_STATUS_OPTIONS


# ── The destructive case ──────────────────────────────────────────────────────

def test_patch_preserves_every_existing_status_option():
    """The whole point. Notion replaces the option list wholesale — dropping the existing ones
    would wipe Scraped/Reviewed/Applied/Retry and orphan every row in the tracker."""
    patch = build_patch(_schema())
    names = [o["name"] for o in patch["Status"]["select"]["options"]]
    for existing in EXISTING_STATUSES:
        assert existing in names, f"{existing} would have been deleted"
    for new in REQUIRED_STATUS_OPTIONS:
        assert new in names


def test_patch_keeps_existing_option_ids_intact():
    """Resending an existing option without its id can make Notion treat it as a new option,
    detaching it from the rows already using it."""
    patch = build_patch(_schema())
    preserved = [o for o in patch["Status"]["select"]["options"] if o["name"] in EXISTING_STATUSES]
    assert all("id" in o for o in preserved)


def test_patch_omits_status_when_only_properties_are_missing():
    """Don't touch the select at all if it's already complete — no needless rewrite of the
    option list means no chance of disturbing it."""
    schema = _schema(statuses=EXISTING_STATUSES + REQUIRED_STATUS_OPTIONS)
    patch = build_patch(schema)
    assert "Status" not in patch
    assert "Apply Channel" in patch


def test_patch_never_includes_an_existing_property():
    schema = _schema(props={"Apply Attempts": {"number": {}}})
    assert "Apply Attempts" not in build_patch(schema)


# ── Runner behavior ───────────────────────────────────────────────────────────

class FakeDatabases:
    def __init__(self, schema):
        self.schema = schema
        self.updates = []

    def retrieve(self, database_id):
        return self.schema

    def update(self, database_id, properties):
        self.updates.append(properties)
        # Mirror a successful Notion patch so the script's readback sees the new state.
        props = dict(self.schema["properties"])
        for name, spec in properties.items():
            props[name] = spec
        self.schema = {**self.schema, "properties": props}


class FakeNotion:
    def __init__(self, schema):
        self.databases = FakeDatabases(schema)


@pytest.fixture
def fake_notion(monkeypatch):
    def _make(schema):
        client = FakeNotion(schema)
        monkeypatch.setattr(sns, "_client", lambda: client)
        monkeypatch.setattr(sns, "NOTION_API_KEY", "fake-key")
        monkeypatch.setattr(sns, "NOTION_DB_ID", "fake-db")
        return client
    return _make


def test_dry_run_writes_nothing(fake_notion, capsys):
    client = fake_notion(_schema())
    assert sns.run(apply=False) == 0
    assert client.databases.updates == []
    assert "dry run" in capsys.readouterr().out.lower()


def test_apply_patches_once_and_verifies(fake_notion, capsys):
    client = fake_notion(_schema())
    assert sns.run(apply=True) == 0
    assert len(client.databases.updates) == 1
    assert "applied" in capsys.readouterr().out.lower()


def test_apply_is_idempotent(fake_notion):
    """Re-running after a successful migration must be a clean no-op, not a second patch."""
    client = fake_notion(_schema())
    sns.run(apply=True)
    assert sns.run(apply=True) == 0
    assert len(client.databases.updates) == 1


def test_missing_api_key_fails_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(sns, "NOTION_API_KEY", "")
    assert sns.run(apply=True) == 1
    assert "notion_api_key" in capsys.readouterr().out.lower()


def test_unreadable_database_fails_cleanly(monkeypatch, capsys):
    class Boom:
        class databases:
            @staticmethod
            def retrieve(database_id):
                raise RuntimeError("unauthorized")
    monkeypatch.setattr(sns, "NOTION_API_KEY", "fake-key")
    monkeypatch.setattr(sns, "NOTION_DB_ID", "fake-db")
    monkeypatch.setattr(sns, "_client", lambda: Boom())
    assert sns.run(apply=True) == 1
    assert "shared" in capsys.readouterr().out.lower()


def test_silent_failure_is_reported_not_celebrated(monkeypatch, fake_notion, capsys):
    """If Notion accepts the patch but doesn't apply it, the script must say so — reporting
    success on an unverified write is the exact failure this whole design guards against."""
    client = fake_notion(_schema())
    monkeypatch.setattr(client.databases, "update", lambda **kw: None)  # accepts, changes nothing
    assert sns.run(apply=True) == 1
    assert "still missing" in capsys.readouterr().out.lower()
