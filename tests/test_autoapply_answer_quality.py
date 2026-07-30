"""Contract tests for the four fast-apply fixes in scripts/autoapply.py.

Each of these guards a defect found by planning the tracker's real Greenhouse jobs
(2026-07-30), not a hypothetical:

1. Identity was the literal "Your"/"Name" marked `ready` — every filled application would
   have submitted under that name.
2. Preset matching was raw substring, so one "years of experience" answer matched none of the
   three phrasings live boards actually use.
3. Free-text answers were never drafted despite the module documenting that the model drafts
   prose — so every per-job essay was hand-written.
4. `_LABEL_RULES` checked work-authorization before sponsorship, so a sponsorship question
   whose label contains "work authorization" was answered from the wrong profile key.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts import autoapply
from scripts.autoapply import (
    _label_matches_pattern, _preset_answer, _resolve_field,
    draft_free_text_answers, _DRAFT_SOURCE,
)


# ── 1. Identity is never a plausible-looking placeholder ──────────────────────
def test_placeholder_name_yields_no_answer():
    """"Your Name" must not derive to first="Your"/last="Name": those read as `ready` and
    would be typed into a real application."""
    from config.settings import _split_display_name
    assert _split_display_name("Your Name") == ("", "")
    assert _split_display_name("") == ("", "")


def test_real_name_splits_and_blank_forces_review():
    from config.settings import _split_display_name
    assert _split_display_name("Ada Lovelace") == ("Ada", "Lovelace")
    assert _split_display_name("Mary Anne Evans") == ("Mary Anne", "Evans")
    assert _split_display_name("Prince") == ("Prince", "")

    # An empty first name must route to human review, never fill blank.
    entry = _resolve_field("First Name", {"name": "first_name", "type": "input_text"},
                           {"first_name": ""}, "")
    assert entry["status"] == "review_required"


# ── 2. Preset matching absorbs real-world phrasing ────────────────────────────
@pytest.mark.parametrize("label", [
    "How many years of experience do you have?",
    "How many years of professional experience do you have developing software?",
    "How many years of industry software engineering experience (not including internships)?",
    "How many years of professional software engineering experience do you have?",
])
def test_years_of_experience_matches_every_live_phrasing(label):
    """All four were seen on live Greenhouse boards; raw substring matched only the first."""
    assert _label_matches_pattern(label.lower(), "years of experience")


def test_short_pattern_words_require_exact_match():
    """A prefix match on a short function word would match unrelated long words:
    "of" must not match "office", which would fire the wrong preset."""
    assert not _label_matches_pattern("years in office experience", "years of experience")


def test_long_pattern_words_allow_prefix_match():
    assert _label_matches_pattern("are you open to relocating for this role?",
                                  "open to relocation")


def test_preset_bank_never_fabricates_a_history_answer():
    """Questions of fact about the candidate's history ship blank on purpose: a fabricated
    "No" is a false statement on a real application."""
    for label in ("Have you ever interviewed at Acme before?",
                  "Were you referred to this position by a current employee?",
                  "Have you previously been employed with Acme?"):
        assert _preset_answer(label) == "", label
        entry = _resolve_field(label, {"name": "q", "type": "input_text"}, {}, "")
        assert entry["status"] == "review_required", label


# ── 3. Free-text drafting ─────────────────────────────────────────────────────
def _free_text_plan():
    return {"fields": [
        {"label": "Why Acme?", "required": True, "type": "textarea",
         "status": "review_required", "value": None, "source": _DRAFT_SOURCE},
        {"label": "First Name", "required": True, "type": "input_text",
         "status": "ready", "value": "Ada", "source": "profile.first_name"},
    ]}


def test_draft_fills_only_free_text_and_leaves_status_alone(monkeypatch):
    monkeypatch.setattr(autoapply, "ai_chat", lambda *a, **k: "I want to work at Acme because...")
    plan = _free_text_plan()
    assert draft_free_text_answers(plan, {"company": "Acme"}, "JD text", "resume text") == 1

    essay, name = plan["fields"]
    assert essay["draft"].startswith("I want to work at Acme")
    # Load-bearing: a draft must NOT become an answer, or the browser would type unreviewed prose.
    assert essay["status"] == "review_required"
    assert essay["value"] is None
    assert "draft" not in name          # non-free-text fields untouched


def test_draft_failure_degrades_to_previous_behavior(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(autoapply, "ai_chat", boom)
    plan = _free_text_plan()
    assert draft_free_text_answers(plan, {"company": "Acme"}, "JD", "resume") == 0
    assert "draft" not in plan["fields"][0]
    assert plan["fields"][0]["status"] == "review_required"


def test_needs_human_reply_is_not_recorded_as_a_draft(monkeypatch):
    monkeypatch.setattr(autoapply, "ai_chat", lambda *a, **k: "NEEDS_HUMAN")
    plan = _free_text_plan()
    assert draft_free_text_answers(plan, {"company": "Acme"}, "JD", "resume") == 0
    assert "draft" not in plan["fields"][0]


def test_no_grounding_material_means_no_draft(monkeypatch):
    """With neither a JD nor resume text there is nothing to ground on, so drafting must not
    run at all rather than invent an answer from the question alone."""
    monkeypatch.setattr(autoapply, "ai_chat",
                        lambda *a, **k: pytest.fail("must not call the model"))
    assert draft_free_text_answers(_free_text_plan(), {"company": "Acme"}, "", "") == 0


def test_drafted_answer_is_labelled_a_draft_in_the_sheet(monkeypatch):
    monkeypatch.setattr(autoapply, "ai_chat", lambda *a, **k: "Grounded prose here.")
    plan = _free_text_plan()
    draft_free_text_answers(plan, {"company": "Acme"}, "JD", "resume")
    plan.setdefault("title", "Engineer")
    rpt = autoapply.readiness_report(plan)
    out = autoapply._answer_sheet_html({"company": "Acme", "title": "Engineer", "url": "u"},
                                       plan, rpt, "greenhouse")
    assert "Grounded prose here." in out
    assert "DRAFT" in out


# ── 4. Sponsorship is never answered from the work-authorization key ──────────
def test_sponsorship_label_containing_work_authorization_uses_sponsorship_key():
    """The real Customer.io label. It contains the substring "work authorization", so the old
    rule order answered it from `work_authorized` — wrong for anyone whose flags differ."""
    profile = {"work_authorized": True, "requires_sponsorship": False}
    entry = _resolve_field(
        "Will you require work authorization/visa sponsorship to work in this country?",
        {"name": "q_sponsor", "type": "input_text"}, profile, "")
    assert entry["source"] == "profile.requires_sponsorship"
    assert entry["value"] is False


def test_plain_work_authorization_label_still_uses_work_authorized():
    profile = {"work_authorized": True, "requires_sponsorship": False}
    entry = _resolve_field("Are you legally authorized to work in the United States?",
                           {"name": "q_auth", "type": "input_text"}, profile, "")
    assert entry["source"] == "profile.work_authorized"
    assert entry["value"] is True


def test_unset_sponsorship_still_never_guessed():
    entry = _resolve_field("Will you require visa sponsorship?",
                           {"name": "q", "type": "input_text"},
                           {"requires_sponsorship": None}, "")
    assert entry["status"] == "review_required"
    assert "never guessed" in entry["source"]
