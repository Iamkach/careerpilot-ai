"""
Phase 1 — pure-function unit tests for scripts/sources.py.

Every test here monkeypatches the module-level config constants (TARGET_ROLES,
MAX_JOB_AGE_DAYS, DROP_UNDATED_JOBS) it depends on to fixed values, rather than relying on
whatever config/settings.py currently has — these functions are pure given their inputs, and
the tests shouldn't break just because someone edits TARGET_ROLES for their own job search.
"""
import datetime
import json

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


# ── _extract_jobposting_jsonld ──────────────────────────────────────────────
# Closes gap #1/#2 from docs/refinement-plans/sourcing/career-site-enrichment-fallback.md:
# generic_url_fetch()'s raw-tag-stripping fallback returns blank company/location and can
# come back near-empty on a JS-rendered SPA shell. JSON-LD JobPosting data is often present
# in the server-rendered <head> even when the visible DOM is client-hydrated.

_JOB_DESCRIPTION = (
    "We are looking for a Senior Backend Engineer to help scale our platform. "
    "Experience with Python, AWS, and distributed systems required. " * 3
)


def _jsonld_html(payload) -> str:
    return (
        "<html><head><title>Careers</title>"
        f'<script type="application/ld+json">{json.dumps(payload)}</script>'
        "</head><body><div id=\"root\"></div></body></html>"
    )


def _job_posting_node(**overrides) -> dict:
    node = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": "Senior Backend Engineer",
        "hiringOrganization": {"@type": "Organization", "name": "Acme Corp"},
        "jobLocation": {
            "@type": "Place",
            "address": {"addressLocality": "Austin", "addressRegion": "TX"},
        },
        "description": _JOB_DESCRIPTION,
    }
    node.update(overrides)
    return node


def test_extract_jobposting_jsonld_single_object():
    html = _jsonld_html(_job_posting_node())
    result = sources._extract_jobposting_jsonld(html)
    assert result == {
        "title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "location": "Austin, TX",
        "description": _JOB_DESCRIPTION.strip(),
    }


def test_extract_jobposting_jsonld_graph_wrapped():
    html = _jsonld_html({
        "@context": "https://schema.org/",
        "@graph": [
            {"@type": "Organization", "name": "Acme Corp"},
            _job_posting_node(),
        ],
    })
    result = sources._extract_jobposting_jsonld(html)
    assert result["title"] == "Senior Backend Engineer"
    assert result["company"] == "Acme Corp"


def test_extract_jobposting_jsonld_list_wrapped():
    html = _jsonld_html([
        {"@type": "WebSite", "name": "Acme Careers"},
        _job_posting_node(),
    ])
    result = sources._extract_jobposting_jsonld(html)
    assert result["company"] == "Acme Corp"


def test_extract_jobposting_jsonld_type_as_list():
    html = _jsonld_html(_job_posting_node(**{"@type": ["JobPosting", "Thing"]}))
    result = sources._extract_jobposting_jsonld(html)
    assert result is not None
    assert result["title"] == "Senior Backend Engineer"


def test_extract_jobposting_jsonld_no_job_posting_type_returns_none():
    html = _jsonld_html({"@type": "Organization", "name": "Acme Corp"})
    assert sources._extract_jobposting_jsonld(html) is None


def test_extract_jobposting_jsonld_malformed_json_does_not_raise():
    html = (
        "<html><head>"
        '<script type="application/ld+json">{not valid json</script>'
        "</head><body></body></html>"
    )
    assert sources._extract_jobposting_jsonld(html) is None


def test_extract_jobposting_jsonld_no_script_tag_returns_none():
    assert sources._extract_jobposting_jsonld("<html><body>hi</body></html>") is None


# ── generic_url_fetch ───────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


def _forbid_headless(monkeypatch):
    """Assert the (expensive) headless-render fallback is never reached when the static
    JSON-LD/raw-text path already succeeded."""
    def _raise(*a, **k):
        raise AssertionError("_headless_fetch should not be called when the static path succeeds")
    monkeypatch.setattr(sources, "_headless_fetch", _raise)


def test_generic_url_fetch_uses_jsonld_even_when_visible_text_is_a_near_empty_spa_shell(
    monkeypatch,
):
    """The core gap-2 fix: a JS-rendered shell whose hydrated body is nearly empty (would
    fail the 200-char guard) still enriches correctly because the JobPosting JSON-LD lives
    in the server-rendered <head> — no need to fall through to a headless render at all."""
    html = _jsonld_html(_job_posting_node())
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResponse(html))
    _forbid_headless(monkeypatch)

    result = sources.generic_url_fetch("https://careers.example.com/job/123")

    assert result == {
        "title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "location": "Austin, TX",
        "description": _JOB_DESCRIPTION.strip(),
    }


def test_generic_url_fetch_falls_back_to_raw_text_when_no_jsonld_present(monkeypatch):
    html = (
        "<html><head><title>Senior Backend Engineer - Job ID 123 | Acme</title></head>"
        f"<body><p>{_JOB_DESCRIPTION}</p></body></html>"
    )
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResponse(html))
    _forbid_headless(monkeypatch)

    result = sources.generic_url_fetch("https://careers.example.com/job/123")

    assert result["title"] == "Senior Backend Engineer - Job ID 123 | Acme"
    assert result["company"] == ""
    assert result["location"] == ""
    assert _JOB_DESCRIPTION.strip() in result["description"]


def test_generic_url_fetch_falls_back_to_headless_render_when_static_path_is_too_short(
    monkeypatch,
):
    """Option B: a genuine SPA shell (no JSON-LD, near-empty static text) still enriches
    once the headless-rendered HTML is run back through the same JSON-LD/raw-text logic."""
    shell_html = "<html><head><title>Careers</title></head><body><div id=\"root\"></div></body></html>"
    rendered_html = _jsonld_html(_job_posting_node())
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResponse(shell_html))
    monkeypatch.setattr(sources, "_headless_fetch", lambda url, **k: rendered_html)

    result = sources.generic_url_fetch("https://careers.example.com/job/123")

    assert result == {
        "title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "location": "Austin, TX",
        "description": _JOB_DESCRIPTION.strip(),
    }


def test_generic_url_fetch_returns_none_when_headless_render_also_comes_up_short(monkeypatch):
    shell_html = "<html><head><title>Careers</title></head><body><div id=\"root\"></div></body></html>"
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResponse(shell_html))
    monkeypatch.setattr(sources, "_headless_fetch", lambda url, **k: shell_html)

    assert sources.generic_url_fetch("https://careers.example.com/job/123") is None


def test_generic_url_fetch_returns_none_when_headless_fetch_itself_fails(monkeypatch):
    shell_html = "<html><head><title>Careers</title></head><body><div id=\"root\"></div></body></html>"
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResponse(shell_html))
    monkeypatch.setattr(sources, "_headless_fetch", lambda url, **k: None)

    assert sources.generic_url_fetch("https://careers.example.com/job/123") is None


# ── _headless_fetch ──────────────────────────────────────────────────────────

def test_headless_fetch_returns_none_gracefully_when_playwright_not_installed(monkeypatch):
    """Playwright is an optional dependency (requirements.txt) — its absence must degrade to
    a None return, never a hard ImportError bubbling up to the caller. Blocks the import
    regardless of whether playwright happens to be installed in whatever environment runs
    this test, so the test is deterministic either way."""
    import builtins
    real_import = builtins.__import__

    def _blocked_import(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("simulated: playwright not installed")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    assert sources._headless_fetch("https://careers.example.com/job/123") is None
