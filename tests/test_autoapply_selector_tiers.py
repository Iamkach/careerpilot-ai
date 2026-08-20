"""
Unit tests for scripts/autoapply_browser.py's selector-tier machinery — `_candidate_selectors()`
and `_attempted_tiers()`. No browser, no Playwright: these are pure string functions and run in
the default suite (see the fixture-driven browser tests in tests/test_autoapply_browser.py for
the live-DOM resolution coverage, including the accessibility-tree tier this module only
describes by name).
"""
from scripts.autoapply_browser import _attempted_tiers, _candidate_selectors


def test_name_tier_comes_first_when_both_name_and_label_present():
    field = {"name": "first_name", "label": "First Name"}
    tiers = [t for t, _ in _candidate_selectors(field)]
    assert tiers[0] == "name"
    assert tiers[1] == "name"
    assert all(t == "xpath_label" for t in tiers[2:])


def test_name_only_field_has_no_xpath_candidates():
    field = {"name": "email", "label": ""}
    sels = _candidate_selectors(field)
    assert [t for t, _ in sels] == ["name", "name"]
    assert sels[0][1] == '[name="email"]'
    assert sels[1][1] == "#email"


def test_label_only_field_has_no_name_candidates():
    field = {"name": "", "label": "How did you hear about this job?"}
    sels = _candidate_selectors(field)
    assert [t for t, _ in sels] == ["xpath_label"] * 3


def test_no_name_and_no_label_yields_nothing():
    assert _candidate_selectors({}) == []


def test_label_is_truncated_and_quote_escaped_in_xpath_candidates():
    long_label = 'Question with "quotes" and ' + "x" * 60
    field = {"name": "", "label": long_label}
    sels = _candidate_selectors(field)
    esc_snippet = long_label.replace('"', '\\"')[:40]
    assert all(esc_snippet in sel for _, sel in sels)
    # never embeds more than the 40-char prefix
    assert all(long_label.replace('"', '\\"')[:41] not in sel for _, sel in sels)


def test_attempted_tiers_mirrors_candidate_selector_presence():
    both = {"name": "phone", "label": "Phone"}
    assert _attempted_tiers(both) == ["name", "aria_exact", "aria_loose", "role_name",
                                       "xpath_label"]

    name_only = {"name": "phone", "label": ""}
    assert _attempted_tiers(name_only) == ["name"]

    label_only = {"name": "", "label": "Phone"}
    assert _attempted_tiers(label_only) == ["aria_exact", "aria_loose", "role_name",
                                             "xpath_label"]

    neither = {"name": "", "label": ""}
    assert _attempted_tiers(neither) == []
