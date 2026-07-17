"""
Phase 1 — pure-function unit tests for scripts/sources.py.

Every test here monkeypatches the module-level config constants (TARGET_ROLES,
MAX_JOB_AGE_DAYS, DROP_UNDATED_JOBS) it depends on to fixed values, rather than relying on
whatever config/settings.py currently has — these functions are pure given their inputs, and
the tests shouldn't break just because someone edits TARGET_ROLES for their own job search.
"""
import datetime

import pytest

from scripts import sources


# ── _norm_company ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Stripe, Inc.", "stripe"),
    ("Stripe Inc", "stripe"),
    ("Stripe", "stripe"),
    ("Stripe Press", "stripepress"),
    ("The Walt Disney Company", "waltdisneycompany"),
    ("Acme, LLC", "acme"),
    ("Acme Corp.", "acme"),
])
def test_norm_company(raw, expected):
    assert sources._norm_company(raw) == expected


# ── _norm_title ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Software Engineer II - Backend", "software engineer 2"),
    ("Software Engineer II", "software engineer 2"),
    ("Senior Software Engineer (Remote)", "senior software engineer"),
    ("Staff Engineer - req 12345", "staff engineer"),
    ("Staff Engineer #1234", "staff engineer"),
    ("Backend Engineer (Hybrid) - San Francisco, CA", "backend engineer"),
])
def test_norm_title(raw, expected):
    assert sources._norm_title(raw) == expected


def test_norm_title_keeps_seniority_words():
    # Seniority tokens are meaningfully different reqs — must not be stripped like a
    # parenthetical/dash clause would be.
    assert "senior" in sources._norm_title("Senior Software Engineer").split()
    assert "staff" in sources._norm_title("Staff Software Engineer").split()


# ── job_fingerprint / collapse_by_fingerprint ─────────────────────────────

def test_job_fingerprint_matches_across_naming_variants():
    fp1 = sources.job_fingerprint("Stripe, Inc.", "Software Engineer II - Backend")
    fp2 = sources.job_fingerprint("Stripe", "Software Engineer II")
    assert fp1 == fp2


def test_job_fingerprint_collapses_same_req_posted_with_different_locations():
    # This is the actual real-world case job_fingerprint exists to solve: the same req
    # posted to a company's LinkedIn page once per office collapses to one row instead of
    # being treated as N distinct openings.
    fp_nyc = sources.job_fingerprint("Stripe", "Senior Software Engineer - New York, NY")
    fp_sf = sources.job_fingerprint("Stripe", "Senior Software Engineer - San Francisco, CA")
    fp_remote = sources.job_fingerprint("Stripe", "Senior Software Engineer (Remote)")
    assert fp_nyc == fp_sf == fp_remote


def test_job_fingerprint_treats_different_seniority_as_different_jobs():
    # The flip side of the same requirement: "Senior X" and "X" must NOT collapse — they are
    # different reqs a candidate would apply to separately. This is the behavior the
    # docstring calls out as deliberate ("seniority tokens are kept, not stripped").
    fp_plain = sources.job_fingerprint("Stripe", "Software Engineer")
    fp_senior = sources.job_fingerprint("Stripe", "Senior Software Engineer")
    fp_staff = sources.job_fingerprint("Stripe", "Staff Software Engineer")
    assert len({fp_plain, fp_senior, fp_staff}) == 3


def test_collapse_by_fingerprint_keeps_highest_priority_source():
    jobs = [
        {"company": "Stripe", "title": "Software Engineer", "source": "indeed", "url": "u1"},
        {"company": "Stripe, Inc.", "title": "Software Engineer", "source": "greenhouse", "url": "u2"},
        {"company": "Stripe", "title": "Software Engineer", "source": "linkedin", "url": "u3"},
    ]
    collapsed = sources.collapse_by_fingerprint(jobs)
    assert len(collapsed) == 1
    assert collapsed[0]["source"] == "greenhouse"  # lower SOURCE_PRIORITY number wins


def test_collapse_by_fingerprint_is_order_independent():
    jobs_a = [
        {"company": "Stripe", "title": "Software Engineer", "source": "indeed", "url": "u1"},
        {"company": "Stripe", "title": "Software Engineer", "source": "greenhouse", "url": "u2"},
    ]
    jobs_b = list(reversed(jobs_a))
    assert sources.collapse_by_fingerprint(jobs_a)[0]["url"] == \
        sources.collapse_by_fingerprint(jobs_b)[0]["url"] == "u2"


def test_collapse_by_fingerprint_keeps_distinct_jobs_separate():
    jobs = [
        {"company": "Stripe", "title": "Software Engineer", "source": "indeed", "url": "u1"},
        {"company": "Databricks", "title": "Software Engineer", "source": "indeed", "url": "u2"},
    ]
    assert len(sources.collapse_by_fingerprint(jobs)) == 2


# ── title_matches_targets ──────────────────────────────────────────────────

def test_title_matches_targets_all_tokens_present(monkeypatch):
    monkeypatch.setattr(sources, "TARGET_ROLES", ["Senior Software Engineer"])
    assert sources.title_matches_targets("Senior Software Engineer, Platform")
    # Order-independent: token order in the title doesn't need to match the role phrase.
    assert sources.title_matches_targets("Software Engineer (Senior)")


def test_title_matches_targets_missing_token_fails(monkeypatch):
    monkeypatch.setattr(sources, "TARGET_ROLES", ["Senior Software Engineer"])
    assert not sources.title_matches_targets("Software Engineer")  # missing "senior"
    assert not sources.title_matches_targets("Senior Product Manager")


def test_title_matches_targets_any_role_matching_is_enough(monkeypatch):
    monkeypatch.setattr(sources, "TARGET_ROLES", ["Backend Engineer", "Data Scientist"])
    assert sources.title_matches_targets("Senior Backend Engineer")
    assert sources.title_matches_targets("Staff Data Scientist")
    assert not sources.title_matches_targets("Frontend Engineer")


# ── _is_fresh ──────────────────────────────────────────────────────────────

def test_is_fresh_none_date_is_fresh_by_default(monkeypatch):
    monkeypatch.setattr(sources, "DROP_UNDATED_JOBS", False)
    assert sources._is_fresh(None) is True


def test_is_fresh_none_date_dropped_when_configured(monkeypatch):
    monkeypatch.setattr(sources, "DROP_UNDATED_JOBS", True)
    assert sources._is_fresh(None) is False


def test_is_fresh_boundary_at_exactly_max_age(monkeypatch):
    monkeypatch.setattr(sources, "MAX_JOB_AGE_DAYS", 14)
    exactly_at_boundary = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    one_day_over = (datetime.date.today() - datetime.timedelta(days=15)).isoformat()
    assert sources._is_fresh(exactly_at_boundary) is True
    assert sources._is_fresh(one_day_over) is False


def test_is_fresh_unparseable_date_falls_back_to_undated_rule(monkeypatch):
    monkeypatch.setattr(sources, "DROP_UNDATED_JOBS", False)
    assert sources._is_fresh("not-a-date") is True
    monkeypatch.setattr(sources, "DROP_UNDATED_JOBS", True)
    assert sources._is_fresh("not-a-date") is False


# ── _to_iso_date ───────────────────────────────────────────────────────────

def test_to_iso_date_epoch_seconds():
    ts = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc).timestamp()
    assert sources._to_iso_date(ts) == "2026-01-15"


def test_to_iso_date_epoch_milliseconds():
    ts_ms = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc).timestamp() * 1000
    assert sources._to_iso_date(ts_ms) == "2026-01-15"


def test_to_iso_date_iso_string_with_z_suffix():
    assert sources._to_iso_date("2026-01-15T10:30:00Z") == "2026-01-15"


def test_to_iso_date_bare_date_string():
    assert sources._to_iso_date("2026-01-15") == "2026-01-15"


def test_to_iso_date_digit_string_epoch_ms():
    ts_ms = int(datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    assert sources._to_iso_date(str(ts_ms)) == "2026-01-15"


def test_to_iso_date_none_or_empty_returns_none():
    assert sources._to_iso_date(None) is None
    assert sources._to_iso_date("") is None


def test_to_iso_date_unparseable_returns_none():
    assert sources._to_iso_date("not a date at all") is None


# ── _parse_salary ──────────────────────────────────────────────────────────

def test_parse_salary_from_dict_range():
    job = {"salaryRange": {"min": 150000, "max": 190000}}
    assert sources._parse_salary(job) == "150000–190000"


def test_parse_salary_from_plain_string():
    job = {"salary": "$150k - $190k"}
    assert sources._parse_salary(job) == "$150k - $190k"


def test_parse_salary_missing_returns_empty_string():
    assert sources._parse_salary({}) == ""


def test_parse_salary_checks_fields_in_priority_order():
    # "salaryRange" is checked before "pay" per the function's key order.
    job = {"pay": "ignored", "salaryRange": "$100k"}
    assert sources._parse_salary(job) == "$100k"
