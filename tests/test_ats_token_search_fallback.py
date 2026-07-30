"""
Tests for discover_tokens()'s DuckDuckGo search-fallback tier (scripts/sources.py):

When the direct name-slug guess misses for a given ATS, discover_tokens() now tries candidate
slugs pulled from a keyless DuckDuckGo HTML search, still verifying each candidate against the
real ATS API via the existing _probe_* functions before accepting it.

  1. The fallback fires only for an ATS the direct guess missed, and stops at the first
     candidate that verifies.
  2. The fallback is skipped entirely when the direct guess already succeeded (no wasted
     search call).
  3. ENABLE_ATS_TOKEN_SEARCH_FALLBACK = False disables the fallback path entirely.
  4. _dork_candidate_slugs() never raises — timeout, non-200, and malformed response all
     degrade to [].
"""
import pytest

from scripts import sources


# ── 1. Fallback fires on a miss and stops at the first verified candidate ────

def test_fallback_tries_candidates_until_one_verifies(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", True)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)

    # Direct guess (slugified company name) misses for every ATS.
    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    def fake_dork(company, domain):
        if domain == "boards.greenhouse.io":
            return ["wrong-candidate", "acme-hq"]
        return []

    monkeypatch.setattr(sources, "_dork_candidate_slugs", fake_dork)

    tried = []

    def verifying_probe(company, slug):
        tried.append(slug)
        return "acme-hq" if slug == "acme-hq" else None

    monkeypatch.setattr(sources, "_probe_greenhouse", verifying_probe)

    tokens = sources.discover_tokens(["Acme Inc"], max_new_probes=5)

    # First entry is the direct slug guess ("acmeinc"), which also misses via verifying_probe;
    # the fallback then tries the dork candidates and stops at the first verified hit.
    assert tried == ["acmeinc", "wrong-candidate", "acme-hq"]
    assert tokens["Acme Inc"]["greenhouse"] == "acme-hq"


# ── 2. Fallback skipped when the direct guess already succeeded ─────────────

def test_fallback_skipped_when_direct_guess_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", True)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)

    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: "acme")
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    dork_calls = []
    monkeypatch.setattr(
        sources, "_dork_candidate_slugs",
        lambda company, domain: dork_calls.append(domain) or [],
    )

    tokens = sources.discover_tokens(["Acme Inc"], max_new_probes=5)

    assert "boards.greenhouse.io" not in dork_calls, "greenhouse already hit — no search needed"
    assert tokens["Acme Inc"]["greenhouse"] == "acme"


# ── 3. Flag off disables the fallback entirely ───────────────────────────────

def test_fallback_disabled_by_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "ATS_TOKENS_PATH", tmp_path / "ats_tokens.json")
    monkeypatch.setattr(sources, "ENABLE_ATS_TOKEN_SEARCH_FALLBACK", False)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)

    monkeypatch.setattr(sources, "_probe_greenhouse", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_lever", lambda c, s: None)
    monkeypatch.setattr(sources, "_probe_ashby", lambda c, s: None)

    dork_calls = []
    monkeypatch.setattr(
        sources, "_dork_candidate_slugs",
        lambda company, domain: dork_calls.append(domain) or [],
    )

    tokens = sources.discover_tokens(["Acme Inc"], max_new_probes=5)

    assert dork_calls == []
    assert tokens["Acme Inc"]["greenhouse"] is None


# ── 4. _dork_candidate_slugs never raises ────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_dork_candidate_slugs_returns_empty_on_non_200(monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResp(429))
    assert sources._dork_candidate_slugs("Acme Inc", "boards.greenhouse.io") == []


def test_dork_candidate_slugs_returns_empty_on_timeout(monkeypatch):
    def raise_timeout(*a, **k):
        raise sources.requests.exceptions.Timeout()

    monkeypatch.setattr(sources.requests, "get", raise_timeout)
    assert sources._dork_candidate_slugs("Acme Inc", "boards.greenhouse.io") == []


def test_dork_candidate_slugs_parses_tokens_from_result_html(monkeypatch):
    html = (
        '<a href="https://boards.greenhouse.io/acme-hq/jobs/123">Acme HQ — SWE</a>'
        '<a href="https://boards.greenhouse.io/acme-hq/jobs/456">Acme HQ — PM</a>'
        '<a href="https://boards.greenhouse.io/other-co/jobs/789">Other Co</a>'
    )
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: _FakeResp(200, html))
    candidates = sources._dork_candidate_slugs("Acme Inc", "boards.greenhouse.io")
    assert candidates == ["acme-hq", "other-co"], "unique, in first-seen order"
