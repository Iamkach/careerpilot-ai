"""
Phase 1 — pure-function unit tests for scripts/utils.py.

matches_company_list / parse_json_response have zero I/O and zero AI dependency, making them
the highest-leverage unit test targets in the repo (parse_json_response backs nearly every
AI-response-parsing path across every stage).
"""
import pytest

from scripts import utils


# ── matches_company_list / _tokens / _strip_suffix / _subseq ──────────────

def test_matches_company_list_exact_match():
    assert utils.matches_company_list("Stripe", ["Stripe", "Databricks"])


def test_matches_company_list_legal_suffix_variant_matches():
    assert utils.matches_company_list("BeaconFire Inc.", ["BeaconFire"])
    assert utils.matches_company_list("Tata Consultancy", ["Tata Consultancy Services"]) is False
    assert utils.matches_company_list("Tata Consultancy Services", ["Tata Consultancy"])


def test_matches_company_list_no_false_positive_substring():
    # The docstring's own called-out false-positive case: "UST" must not match "Customer.io"
    # via raw substring matching.
    assert not utils.matches_company_list("Customer.io", ["UST"])
    assert not utils.matches_company_list("UST", ["Customer.io"])


def test_matches_company_list_true_positive_still_works():
    assert utils.matches_company_list("UST Global", ["UST"])


def test_matches_company_list_empty_inputs():
    assert not utils.matches_company_list("", ["Stripe"])
    assert not utils.matches_company_list("Stripe", [])


def test_tokens_lowercases_and_splits_on_non_alnum():
    assert utils._tokens("Stripe, Inc.") == ["stripe", "inc"]
    assert utils._tokens("") == []


def test_strip_suffix_trims_trailing_legal_suffix_only():
    assert utils._strip_suffix(["acme", "corp"]) == ["acme"]
    assert utils._strip_suffix(["acme"]) == ["acme"]
    # Leading tokens are not touched by _strip_suffix (only trailing, unlike sources._norm_company)
    assert utils._strip_suffix(["the", "acme"]) == ["the", "acme"]


def test_subseq_contiguous_token_boundary_match():
    assert utils._subseq(["tata", "consultancy", "services"], ["tata", "consultancy"])
    assert not utils._subseq(["tata", "consultancy", "services"], ["consultancy", "tata"])
    assert not utils._subseq(["a", "tata", "b", "consultancy"], ["tata", "consultancy"])
    assert not utils._subseq(["anything"], [])


# ── parse_json_response ─────────────────────────────────────────────────────

def test_parse_json_response_plain_object():
    assert utils.parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_plain_array():
    assert utils.parse_json_response('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_parse_json_response_fenced_json_block():
    text = '```json\n{"a": 1}\n```'
    assert utils.parse_json_response(text) == {"a": 1}


def test_parse_json_response_fenced_block_without_json_tag():
    text = '```\n{"a": 1}\n```'
    assert utils.parse_json_response(text) == {"a": 1}


def test_parse_json_response_prose_wrapped_object():
    text = 'Sure, here is the result:\n{"a": 1}\nLet me know if you need anything else.'
    assert utils.parse_json_response(text) == {"a": 1}


def test_parse_json_response_prose_wrapped_array():
    text = 'Here you go:\n[{"a": 1}, {"b": 2}]\nDone.'
    assert utils.parse_json_response(text) == [{"a": 1}, {"b": 2}]


def test_parse_json_response_embedded_braces_in_string_values():
    text = '{"note": "use {curly} braces in prose"}'
    assert utils.parse_json_response(text) == {"note": "use {curly} braces in prose"}


def test_parse_json_response_malformed_raises_value_error():
    with pytest.raises(ValueError):
        utils.parse_json_response("this is not json at all")


def test_parse_json_response_truncated_json_raises_value_error():
    # A response cut off mid-object/array (e.g. a real max_tokens truncation) must raise,
    # never silently return a partial/garbage result.
    with pytest.raises(ValueError):
        utils.parse_json_response('{"a": 1, "b": [1, 2, 3')


def test_parse_json_response_empty_string_raises_value_error():
    with pytest.raises(ValueError):
        utils.parse_json_response("")


# ── score-property readers: absent must stay distinct from a real 0 ──────────
# _prop_number_opt backs ATS Match Score, where "unscored" (None) must never read
# back as a numeric 0 (see _unscored()/score_jobs_batch's contract). _prop_number
# keeps its 0 default for the counter properties whose (x or 0)+1 increments rely on it.

def test_prop_number_opt_absent_returns_none():
    assert utils._prop_number_opt({}, "ATS Match Score") is None
    assert utils._prop_number_opt({"ATS Match Score": {}}, "ATS Match Score") is None
    assert utils._prop_number_opt({"ATS Match Score": {"number": None}}, "ATS Match Score") is None


def test_prop_number_opt_real_zero_stays_zero():
    assert utils._prop_number_opt({"ATS Match Score": {"number": 0}}, "ATS Match Score") == 0
    assert utils._prop_number_opt({"ATS Match Score": {"number": 72}}, "ATS Match Score") == 72


def test_prop_number_counter_default_unchanged():
    # Counters (Scoring/Enrichment/Apply Attempts, Applicant Count) still default to 0
    # so (x or 0)+1 increments work whether the property is absent or a real 0.
    assert utils._prop_number({}, "Scoring Attempts") == 0
    assert utils._prop_number({"Scoring Attempts": {"number": 0}}, "Scoring Attempts") == 0
    assert utils._prop_number({"Scoring Attempts": {"number": 3}}, "Scoring Attempts") == 3


def test_page_to_job_unscored_yields_none_not_zero():
    page = {"id": "pg1", "properties": {}}
    job = utils._page_to_job(page)
    assert job["ats"] is None
    assert job["ats_score"] is None


def test_page_to_job_real_zero_preserved():
    page = {"id": "pg2", "properties": {"ATS Match Score": {"number": 0}}}
    job = utils._page_to_job(page)
    assert job["ats"] == 0
    assert job["ats_score"] == 0
