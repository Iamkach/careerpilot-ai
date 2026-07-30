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


def test_init_wizard_reuses_existing_db_when_declined(tmp_path, monkeypatch, cleanup_env):
    """A re-run of --init on an already-provisioned fork must see NOTION_DB_ID (loaded from
    .env into os.environ, mirroring what `import config.settings` does as a side effect at the
    top of init_wizard()) and skip re-provisioning when the user declines the "provision a NEW
    workspace" prompt. Regression test: init_wizard() previously read os.environ directly
    without ever importing config.settings first, so a real .env-only NOTION_DB_ID (not already
    present in the process env) was invisible here and every re-run fell through to
    re-provisioning instead of reusing the existing tracker.
    """
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setenv("NOTION_API_KEY", "tok-existing")
    monkeypatch.setenv("NOTION_DB_ID", "already-provisioned-db")
    monkeypatch.setattr(run, "check_setup", lambda: None)

    # Token prompt (keep current) → decline reprovisioning → decline profile block → decline CI sync.
    answers = iter(["", "n", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))

    provision_calls = []
    monkeypatch.setattr("scripts.provision_notion.provision",
                        lambda parent: provision_calls.append(parent) or ("x", "y", "z"))

    assert run.init_wizard() == 0
    assert provision_calls == []  # never provisioned — existing DB was reused


def test_init_wizard_provisions_and_persists_ids(tmp_path, monkeypatch, cleanup_env):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setenv("NOTION_DB_ID", "")  # simulate an un-provisioned fork
    monkeypatch.setattr(run, "check_setup", lambda: None)

    # Decline the two trailing skippable blocks (profile + CI sync) so this test stays
    # focused on the Notion-provisioning path.
    answers = iter(["tok-123", "parent-xyz", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    monkeypatch.setattr("scripts.provision_notion.provision",
                        lambda parent: ("trk-id", "scr-id", "res-id"))

    assert run.init_wizard() == 0

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "NOTION_API_KEY=tok-123" in env_text
    assert "NOTION_DB_ID=trk-id" in env_text
    assert "NOTION_SCRATCH_PAGE_ID=scr-id" in env_text
    assert "NOTION_RESTRICTED_COMPANIES_PAGE_ID=res-id" in env_text
    # The declined profile block wrote no config/profile.json.
    assert not (tmp_path / "config" / "profile.json").exists()


# ── run.py --init wizard: profile section (2b) ────────────────────────────────

def test_init_wizard_profile_section_writes_profile_json(tmp_path, monkeypatch, cleanup_env):
    """Accepting the profile block writes config/profile.json with the typed answers and leaves
    the unrelated .env lines the Notion step wrote untouched."""
    import json
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setenv("NOTION_DB_ID", "")
    monkeypatch.setattr(run, "check_setup", lambda: None)
    # Seed a profile.example.json so the seed-from-example path is exercised.
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "profile.example.json").write_text(
        json.dumps({"name": "Your Name", "ai_provider": "claude"}), encoding="utf-8")

    answers = iter([
        "tok-123", "parent-xyz",        # Notion token + parent page
        "",                              # profile block: "Y" (accept)
        "Fork User",                     # name
        "fork@example.com",              # email
        "A short bio.",                  # bio
        "Backend Engineer, SRE",         # target roles (comma-separated)
        "Stripe, Linear",                # target companies
        "config/resume.txt",             # resume text path
        "config/resume.docx",            # resume .docx path
        "gemini",                        # AI provider
        "n",                             # CI sync: skip
    ])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    monkeypatch.setattr("scripts.provision_notion.provision",
                        lambda parent: ("trk-id", "scr-id", "res-id"))

    assert run.init_wizard() == 0

    profile = json.loads((tmp_path / "config" / "profile.json").read_text(encoding="utf-8"))
    assert profile["name"] == "Fork User"
    assert profile["email"] == "fork@example.com"
    assert profile["target_roles"] == ["Backend Engineer", "SRE"]
    assert profile["target_companies"] == ["Stripe", "Linear"]
    assert profile["ai_provider"] == "gemini"

    # .env lines from the Notion step are intact.
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "NOTION_API_KEY=tok-123" in env_text
    assert "NOTION_DB_ID=trk-id" in env_text


# ── run.py _sync_ci_secrets() (2g) ────────────────────────────────────────────

class _FakeCompleted:
    def __init__(self, returncode=0):
        self.returncode = returncode


def _seed_ci_files(tmp_path):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "profile.json").write_text('{"name": "Fork User"}', encoding="utf-8")


def test_sync_ci_secrets_pushes_via_gh(tmp_path, monkeypatch, cleanup_env):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    _seed_ci_files(tmp_path)
    monkeypatch.setenv("NOTION_API_KEY", "notion-key")
    monkeypatch.setenv("NOTION_DB_ID", "db-123")
    monkeypatch.setenv("APIFY_API_TOKEN", "apify-tok")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "")  # empty → skipped
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")  # accept the [Y/n]

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "input": kwargs.get("input")})
        return _FakeCompleted(returncode=0)  # gh present + authed, every set succeeds

    monkeypatch.setattr(run.subprocess, "run", fake_run)

    run._sync_ci_secrets()  # must not raise

    set_calls = {c["cmd"][3]: c["input"] for c in calls if c["cmd"][:3] == ["gh", "secret", "set"]}
    assert set_calls["NOTION_API_KEY"] == "notion-key"
    assert set_calls["NOTION_DB_ID"] == "db-123"
    assert set_calls["APIFY_API_TOKEN"] == "apify-tok"
    assert set_calls["ANTHROPIC_API_KEY"] == "sk-ant"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in set_calls  # empty value skipped
    assert set_calls["PROFILE_JSON"] == '{"name": "Fork User"}'
    # Resume files are tracked in git as usual — never pushed as CI secrets.
    assert "RESUME_TXT" not in set_calls
    assert "RESUME_DOCX_BASE64" not in set_calls


def test_sync_ci_secrets_falls_back_to_printed_commands_when_gh_absent(tmp_path, monkeypatch, cleanup_env, capsys):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    _seed_ci_files(tmp_path)
    monkeypatch.setenv("NOTION_DB_ID", "db-123")
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("gh not installed")  # gh binary missing

    monkeypatch.setattr(run.subprocess, "run", fake_run)

    run._sync_ci_secrets()  # must NOT raise

    out = capsys.readouterr().out
    assert "gh secret set" in out
    assert "gh secret set NOTION_DB_ID --body" in out
    assert "gh secret set PROFILE_JSON < config/profile.json" in out
    assert "RESUME_TXT" not in out
    assert "RESUME_DOCX_BASE64" not in out
