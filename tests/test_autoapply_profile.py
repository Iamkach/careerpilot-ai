"""
Tests for scripts/autoapply_profile.py — the one-time Stage 7 answer wizard — and for
Stage 7's --dry-run sampling mode.

The wizard's job is to make the eligibility answers editable without touching settings.py.
Two behaviors matter most: pressing Enter must never silently change an answer, and there must
be a way to *un*-set a wrong eligibility answer (back to "always ask me") — otherwise a typo on
a disqualifying question is permanent.
"""
import json

import pytest

from scripts import autoapply, autoapply_profile as ap
from scripts.autoapply_profile import (
    run_wizard, load_profile, save_profile, build_profile, _parse_yesno, QUESTIONS,
)


def _answers(**over):
    """One canned answer per question, in QUESTIONS order, overridable by key."""
    return [over.get(key, "") for _section, key, _prompt, _kind in QUESTIONS]


def _feed(answers):
    it = iter(answers)
    return lambda _prompt: next(it)


# ── yes/no parsing ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("y", True), ("yes", True), ("Y", True), ("1", True),
    ("n", False), ("no", False), ("0", False),
])
def test_parse_yesno_accepts_common_forms(raw, expected):
    assert _parse_yesno(raw, None) is expected


def test_blank_keeps_the_current_answer():
    assert _parse_yesno("", True) is True
    assert _parse_yesno("", False) is False


def test_clear_unsets_back_to_always_ask():
    """A wrong answer to a disqualifying question must be reversible — 'clear' returns the
    field to None, which the planner treats as 'never guess, always ask'."""
    assert _parse_yesno("clear", True) is None
    assert _parse_yesno("-", False) is None


def test_garbage_does_not_flip_an_eligibility_answer():
    """Unparseable input must not be read as a yes. Silently flipping a sponsorship answer
    because someone typed 'maybe' is exactly the failure this pipeline refuses to allow."""
    assert _parse_yesno("maybe", False) is False
    assert _parse_yesno("idk", None) is None


# ── Wizard flow ───────────────────────────────────────────────────────────────

def test_wizard_records_answers_into_the_right_sections():
    answers = _answers(phone="555-0100", **{"notice period": "2 weeks", "gender": "Male"})
    profile = run_wizard(input_fn=_feed(answers), existing={})
    assert profile["profile"]["phone"] == "555-0100"
    assert profile["presets"]["notice period"] == "2 weeks"
    assert profile["eeo"]["gender"] == "Male"


def test_pressing_enter_through_everything_changes_nothing():
    existing = {"profile": {"phone": "555-0100", "work_authorized": True},
                "presets": {"notice period": "2 weeks"},
                "eeo": {"gender": "Male"}}
    profile = run_wizard(input_fn=_feed(_answers()), existing=existing)
    assert profile["profile"]["phone"] == "555-0100"
    assert profile["profile"]["work_authorized"] is True
    assert profile["presets"]["notice period"] == "2 weeks"
    assert profile["eeo"]["gender"] == "Male"


def test_wizard_captures_eligibility_as_booleans_not_strings():
    """The planner distinguishes True/False (a real answer) from None (unknown). A string
    'yes' would be truthy but wouldn't render as a proper Yes/No selection."""
    profile = run_wizard(
        input_fn=_feed(_answers(work_authorized="y", requires_sponsorship="n")), existing={})
    assert profile["profile"]["work_authorized"] is True
    assert profile["profile"]["requires_sponsorship"] is False


def test_wizard_can_clear_an_eligibility_answer():
    existing = {"profile": {"requires_sponsorship": True}}
    profile = run_wizard(input_fn=_feed(_answers(requires_sponsorship="clear")), existing=existing)
    assert profile["profile"]["requires_sponsorship"] is None


def test_wizard_can_clear_a_text_field():
    existing = {"presets": {"notice period": "2 weeks"}}
    profile = run_wizard(input_fn=_feed(_answers(**{"notice period": "clear"})),
                         existing=existing)
    assert profile["presets"]["notice period"] == ""


def test_enter_on_an_eeo_prompt_keeps_the_settings_default(monkeypatch):
    """Regression: prompts seed from the *effective* value (settings default overlaid with any
    saved answer), not from the saved file alone. Seeding from the file showed 'not set' for a
    field that has a real default, and pressing Enter then saved that blank over
    'Decline To Self Identify' — silently turning a deliberate decline into an empty answer on
    a live application."""
    monkeypatch.setattr(ap, "effective_defaults", lambda: {
        "profile": {}, "presets": {}, "eeo": {"gender": "Decline To Self Identify"}})
    profile = run_wizard(input_fn=_feed(_answers()), existing={})
    assert profile["eeo"]["gender"] == "Decline To Self Identify"


def test_blank_eeo_preset_is_not_filled_as_an_empty_answer(monkeypatch):
    """Defense in depth for the same bug, at the planner: if an EEO preset does end up blank,
    the field must go to human review rather than submitting an empty demographic answer."""
    monkeypatch.setattr(autoapply, "EEO_RESPONSES", {"gender": ""})
    plan = autoapply.build_application_plan({"questions": [
        {"label": "Gender", "required": False,
         "fields": [{"name": "gender", "type": "input_text"}]}]})
    assert plan["fields"][0]["status"] == "review_required"


def test_say_survives_a_cp1252_console(monkeypatch, capsys):
    """Regression: the wizard's success message contains a check mark, and a bare print()
    raised UnicodeEncodeError on a Windows cp1252 console — after the profile had already been
    written, so the user saw a traceback on a run that actually succeeded."""
    calls = []
    real_print = print

    def flaky_print(msg=""):
        if not calls:
            calls.append(msg)
            raise UnicodeEncodeError("charmap", "✓", 0, 1, "undefined")
        real_print(msg)

    monkeypatch.setattr("builtins.print", flaky_print)
    ap.say("✓ Saved")
    monkeypatch.undo()
    assert "Saved" in capsys.readouterr().out


def test_build_profile_preserves_unasked_existing_keys():
    """Hand-edited keys the wizard doesn't ask about must survive a re-run."""
    existing = {"presets": {"custom question": "custom answer"}}
    profile = build_profile({("profile", "phone"): "555"}, existing)
    assert profile["presets"]["custom question"] == "custom answer"


# ── Persistence ───────────────────────────────────────────────────────────────

def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "application_profile.json"
    data = {"profile": {"phone": "555", "work_authorized": True}, "presets": {}, "eeo": {}}
    save_profile(data, path)
    assert load_profile(path) == data


def test_missing_profile_file_is_not_an_error(tmp_path):
    assert load_profile(tmp_path / "nope.json") == {}


def test_corrupt_profile_file_degrades_to_defaults(tmp_path):
    """A broken JSON file must never break a pipeline run — the settings.py defaults stand."""
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_profile(path) == {}


def test_saved_file_is_valid_json(tmp_path):
    path = tmp_path / "p.json"
    save_profile({"profile": {"phone": "555"}}, path)
    assert json.loads(path.read_text(encoding="utf-8"))["profile"]["phone"] == "555"


# ── settings overlay ──────────────────────────────────────────────────────────

def test_settings_overlay_applies_saved_answers(tmp_path, monkeypatch):
    """The overlay is what makes the wizard worth having: saved answers must win over the
    checked-in defaults without anyone editing settings.py."""
    profile_defaults = {"phone": "", "work_authorized": None}
    presets_defaults = {"notice period": ""}
    eeo_defaults = {"gender": "Decline To Self Identify"}

    saved = {"profile": {"phone": "555-0100", "work_authorized": True},
             "presets": {"notice period": "2 weeks"},
             "eeo": {"gender": "Male"}}
    path = tmp_path / "application_profile.json"
    path.write_text(json.dumps(saved), encoding="utf-8")

    # Mirror _apply_saved_profile()'s merge against local dicts.
    for section, target in (("profile", profile_defaults), ("presets", presets_defaults),
                            ("eeo", eeo_defaults)):
        target.update(json.loads(path.read_text(encoding="utf-8"))[section])

    assert profile_defaults["phone"] == "555-0100"
    assert profile_defaults["work_authorized"] is True
    assert presets_defaults["notice period"] == "2 weeks"
    assert eeo_defaults["gender"] == "Male"


# ── Stage 7 --dry-run ─────────────────────────────────────────────────────────

@pytest.fixture
def stage7(monkeypatch, tmp_path, patch_notion_db):
    monkeypatch.setattr(autoapply, "APPLICATIONS_DIR", str(tmp_path))
    monkeypatch.setattr(autoapply, "ensure_dirs", lambda: None)
    monkeypatch.setattr(autoapply, "APPLICATION_PROFILE",
                        {"first_name": "A", "last_name": "B", "email": "a@b.c",
                         "phone": "555", "work_authorized": True, "requires_sponsorship": True})
    db = patch_notion_db(autoapply)
    db.known_statuses = autoapply.WRITABLE_STATUSES | {"Resume Tailored"}
    return db


def _seed(db, tmp_path, **over):
    resume = tmp_path / "resume.docx"
    resume.write_text("resume")
    fields = {"title": "Backend Engineer", "company": "Acme Corp", "ats_score": 80,
              "url": "https://careers.acme.com/apply/1", "resume_link": resume.as_uri()}
    fields.update(over)
    return db.seed(status="Resume Tailored", **fields)


def test_dry_run_makes_no_notion_writes(stage7, tmp_path):
    """The whole point of sampling: evaluate the output on real jobs while the tracker stays
    untouched, so the run is repeatable."""
    page_id = _seed(stage7, tmp_path)
    autoapply.run(dry_run=True)
    assert stage7._pages[page_id]["status"] == "Resume Tailored"
    assert "apply_channel" not in stage7._pages[page_id]


def test_dry_run_still_writes_answer_sheets(stage7, tmp_path):
    """A dry run that produced nothing to look at would be useless for evaluating the stage."""
    _seed(stage7, tmp_path)
    autoapply.run(dry_run=True)
    assert list(tmp_path.glob("*.html"))


def test_dry_run_is_repeatable(stage7, tmp_path):
    page_id = _seed(stage7, tmp_path)
    autoapply.run(dry_run=True)
    autoapply.run(dry_run=True)
    assert stage7._pages[page_id]["status"] == "Resume Tailored"


def test_dry_run_never_opens_a_browser(stage7, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(autoapply, "_fill_one", lambda *a, **k: called.append(a))
    _seed(stage7, tmp_path, url="https://boards.greenhouse.io/acme/jobs/1")
    autoapply.run(dry_run=True, fill=True)
    assert called == []


def test_limit_overrides_the_daily_cap(stage7, tmp_path, monkeypatch):
    monkeypatch.setattr(autoapply, "AUTOAPPLY_DAILY_CAP", 10)
    for i in range(5):
        _seed(stage7, tmp_path, company=f"Co{i}")
    autoapply.run(dry_run=True, limit=2)
    assert len(list(tmp_path.glob("*.html"))) == 2
