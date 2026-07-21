"""Phase 1 — unit test for stage6_negotiate.get_company_type (trivial hardcoded-list
exact-match function, cheap to lock in)."""
import pytest

from scripts import stage6_negotiate as stage6


@pytest.mark.parametrize("company", ["google", "Google", "GOOGLE", "meta", "apple", "amazon",
                                      "netflix", "microsoft"])
def test_known_faang_company_case_insensitive(company):
    assert stage6.get_company_type(company) == "FAANG / large public tech"


@pytest.mark.parametrize("company", ["Stripe", "Databricks", "Acme Corp", ""])
def test_unknown_company_falls_back_to_default(company):
    assert stage6.get_company_type(company) == "tech company (startup or mid-size)"


def test_exact_match_only_no_substring_or_suffix_handling():
    # Characterizes today's behavior: unlike matches_company_list, this is a bare exact
    # lowercase match — "Google LLC" does NOT match "google".
    assert stage6.get_company_type("Google LLC") == "tech company (startup or mid-size)"
