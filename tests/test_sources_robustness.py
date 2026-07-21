"""
Tests for scripts/sources.py robustness fixes (PR #11 review):

  1. _apify_run() raises when the poll budget runs out instead of falling through to fetch a
     still-running run's partial dataset — a silent partial that looked identical to a
     genuinely empty search.
  2. Every Apify HTTP call passes a timeout (the board sources always did; these three didn't,
     so a hung connection blocked the whole run).
  3. enrich_job_url() routes on a parsed-hostname label boundary, so neither a lookalike
     registrable domain nor a path/query substring reaches the wrong ATS enrichment path.
  4. _to_iso_date() no longer uses the deprecated utcfromtimestamp().
  5. discover_tokens() stops probing once its budget is spent.
"""
import datetime
import warnings

import pytest

from scripts import sources


# ── 1 + 2. _apify_run poll budget and timeouts ───────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _patch_apify(monkeypatch, statuses, calls):
    """Stub requests.post/get for _apify_run. `statuses` is consumed one per poll."""
    remaining = list(statuses)

    def fake_post(url, **kwargs):
        calls.append({"method": "post", "url": url, "timeout": kwargs.get("timeout")})
        return _FakeResp({"data": {"id": "run-1"}})

    def fake_get(url, **kwargs):
        calls.append({"method": "get", "url": url, "timeout": kwargs.get("timeout")})
        if "/datasets/" in url:
            return _FakeResp([{"title": "a job"}])
        status = remaining.pop(0) if remaining else "RUNNING"
        return _FakeResp({"data": {"status": status, "defaultDatasetId": "ds-1"}})

    monkeypatch.setattr(sources.requests, "post", fake_post)
    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)


def test_apify_run_raises_when_poll_budget_exhausted(monkeypatch):
    """Still RUNNING when the budget runs out => RuntimeError, NOT a partial dataset. The old
    loop fell through and returned whatever the still-running run had produced so far."""
    calls = []
    _patch_apify(monkeypatch, ["RUNNING", "RUNNING", "RUNNING"], calls)

    with pytest.raises(RuntimeError, match="did not finish within"):
        sources._apify_run("some~actor", {}, poll=3)

    assert not any("/datasets/" in c["url"] for c in calls), \
        "fetched the dataset of a run that never finished"


def test_apify_run_returns_items_on_success(monkeypatch):
    calls = []
    _patch_apify(monkeypatch, ["RUNNING", "SUCCEEDED"], calls)
    assert sources._apify_run("some~actor", {}, poll=5) == [{"title": "a job"}]


def test_apify_run_raises_on_failed_run(monkeypatch):
    calls = []
    _patch_apify(monkeypatch, ["FAILED"], calls)
    with pytest.raises(RuntimeError, match="Apify run FAILED"):
        sources._apify_run("some~actor", {}, poll=5)


def test_apify_run_never_polls_raises_rather_than_unbound(monkeypatch):
    """poll=0 used to raise UnboundLocalError on `status_r`."""
    calls = []
    _patch_apify(monkeypatch, [], calls)
    with pytest.raises(RuntimeError, match="did not finish within"):
        sources._apify_run("some~actor", {}, poll=0)


def test_every_apify_http_call_has_a_timeout(monkeypatch):
    """A hung connection must not block the run indefinitely — the board sources always passed
    timeout=15; these three passed none."""
    calls = []
    _patch_apify(monkeypatch, ["SUCCEEDED"], calls)
    sources._apify_run("some~actor", {}, poll=5)

    assert calls, "no HTTP calls recorded"
    assert all(c["timeout"] is not None for c in calls), \
        f"Apify call(s) without a timeout: {[c for c in calls if c['timeout'] is None]}"


# ── 3. Hostname-boundary routing ─────────────────────────────────────────────

@pytest.mark.parametrize("url, domain, expected", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse.io", True),
    ("https://greenhouse.io/acme/jobs/1",        "greenhouse.io", True),
    ("https://job-boards.greenhouse.io/x/jobs/2", "greenhouse.io", True),
    # Lookalike registrable domain — the substring check matched this.
    ("https://evilgreenhouse.io/acme/jobs/1",    "greenhouse.io", False),
    ("https://notgreenhouse.io/jobs/1",          "greenhouse.io", False),
    # Substring living in the path/query rather than the host.
    ("https://acme.com/careers?ref=greenhouse.io", "greenhouse.io", False),
    ("https://acme.com/greenhouse.io/jobs/1",    "greenhouse.io", False),
    ("https://jobs.lever.co/acme/abc",           "lever.co",      True),
    ("https://mylever.co/acme/abc",              "lever.co",      False),
    ("https://jobs.ashbyhq.com/acme/x",          "ashbyhq.com",   True),
    ("not a url at all",                          "greenhouse.io", False),
])
def test_host_matches_is_label_boundary_anchored(url, domain, expected):
    assert sources.host_matches(url, domain) is expected


def test_enrich_job_url_does_not_route_lookalike_domains_to_ats_paths(monkeypatch):
    """A lookalike host must fall through to the generic fetch, not to the Greenhouse API
    path (which would parse a token out of an attacker-chosen URL)."""
    routed = []
    monkeypatch.setattr(sources, "greenhouse_job_by_url", lambda u: routed.append("gh"))
    monkeypatch.setattr(sources, "lever_job_by_url",      lambda u: routed.append("lever"))
    monkeypatch.setattr(sources, "ashby_job_by_url",      lambda u: routed.append("ashby"))
    monkeypatch.setattr(sources, "generic_url_fetch",     lambda u: routed.append("generic"))

    sources.enrich_job_url("https://evilgreenhouse.io/acme/jobs/1")
    sources.enrich_job_url("https://acme.com/careers?ref=lever.co")
    assert routed == ["generic", "generic"]

    routed.clear()
    sources.enrich_job_url("https://boards.greenhouse.io/acme/jobs/1")
    sources.enrich_job_url("https://jobs.lever.co/acme/abcdef01234567890123")
    assert routed == ["gh", "lever"]


# ── 4. No deprecated datetime API ────────────────────────────────────────────

def test_to_iso_date_epoch_does_not_warn():
    """utcfromtimestamp() is deprecated and scheduled for removal; the epoch path must use a
    timezone-aware conversion instead."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert sources._to_iso_date(1_700_000_000) == "2023-11-14"
        assert sources._to_iso_date(1_700_000_000_000) == "2023-11-14"
        assert sources._to_iso_date("1700000000000") == "2023-11-14"


def test_to_iso_date_epoch_matches_utc_not_local():
    """Guard the semantics the fix preserves: epoch => the UTC calendar date."""
    expected = datetime.datetime.fromtimestamp(
        1_700_000_000, datetime.timezone.utc
    ).date().isoformat()
    assert sources._to_iso_date(1_700_000_000) == expected


# ── 5. discover_tokens stops at its probe budget ─────────────────────────────

def test_discover_tokens_stops_probing_at_budget(monkeypatch, tmp_path):
    """Once max_new_probes is spent, the loop should stop rather than spin over every
    remaining company doing nothing."""
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    seen = []

    def spy(company, slug):
        seen.append(company)
        return None

    monkeypatch.setattr(sources, "_probe_greenhouse", spy)
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)

    companies = [f"Company {i}" for i in range(10)]
    tokens = sources.discover_tokens(companies, max_new_probes=3)

    assert seen == companies[:3]
    assert len(tokens) == 3, "companies past the budget should be left for a later run"
