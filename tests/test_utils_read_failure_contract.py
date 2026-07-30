"""
Tests for the Notion-read and AI-retry contracts in scripts/utils.py (PR #11 review fixes).

The governing rule, already established by db_get_all_jobs(): a *failed read* must never be
reported as a *successful empty result*. Callers act on emptiness by creating rows, so a
swallowed read failure duplicates the tracker — the one direction that can't be undone by
re-running. Two readers still swallowed:

  - get_notion_jobs_by_status() used a raw single-POST read: no pagination (silently truncated
    at Notion's 100-row page), and `[] if not resp.ok` on failure.
  - db_find_job_by_url() returned None (= "no such job") on any exception.

Also covered: _is_transient_error()'s HTTP-status matching (bare substrings turned permanent
failures into retries) and _chat_claude_code()'s ANTHROPIC_API_KEY environment handling.
"""
import os

import pytest

from scripts import utils


# ── 1. get_notion_jobs_by_status: pagination + raise-on-failure ──────────────

def _page(page_id, url, status="Interested"):
    return {
        "id": page_id,
        "properties": {
            "Job Title": {"title": [{"plain_text": f"Job {page_id}"}]},
            "Company":   {"rich_text": [{"plain_text": "Acme"}]},
            "Location":  {"rich_text": [{"plain_text": "Remote"}]},
            "Job URL":   {"url": url},
            "Status":    {"select": {"name": status}},
        },
    }


def test_get_notion_jobs_by_status_follows_pagination(monkeypatch):
    """The old raw POST ignored has_more, silently truncating at one Notion page. Going
    through _query_db() means a tracker with >100 Interested rows is read in full."""
    monkeypatch.setattr(utils, "NOTION_API_KEY", "fake-key")
    pages = [_page(f"p{i}", f"https://example.com/{i}") for i in range(150)]

    calls = []

    def fake_query(filter_=None, sorts=None):
        calls.append(filter_)
        return pages

    monkeypatch.setattr(utils, "_query_db", fake_query)

    jobs = utils.get_notion_jobs_by_status("Interested")

    assert len(jobs) == 150
    assert calls == [{"property": "Status", "select": {"equals": "Interested"}}]


def test_get_notion_jobs_by_status_raises_on_read_failure(monkeypatch):
    """A failed read must not look like 'no Interested jobs'."""
    monkeypatch.setattr(utils, "NOTION_API_KEY", "fake-key")

    def boom(filter_=None, sorts=None):
        raise ConnectionError("notion unreachable")

    monkeypatch.setattr(utils, "_query_db", boom)

    with pytest.raises(RuntimeError, match="read failed"):
        utils.get_notion_jobs_by_status("Interested")


def test_get_notion_jobs_by_status_still_noops_without_a_key(monkeypatch):
    """Unconfigured Notion is not a read failure — it stays an empty list."""
    monkeypatch.setattr(utils, "NOTION_API_KEY", "")
    assert utils.get_notion_jobs_by_status("Interested") == []


def test_get_notion_jobs_by_status_skips_rows_without_a_url(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_API_KEY", "fake-key")
    monkeypatch.setattr(utils, "_query_db", lambda filter_=None, sorts=None: [
        _page("p1", "https://example.com/1"),
        _page("p2", None),
    ])
    jobs = utils.get_notion_jobs_by_status("Interested")
    assert [j["url"] for j in jobs] == ["https://example.com/1"]


# ── 2. db_find_job_by_url: raise, don't report "not found" ───────────────────

def test_db_find_job_by_url_raises_on_read_failure(monkeypatch):
    """None means "no such job", which callers act on by creating a row. A read failure
    reported as None duplicates the tracker."""
    def boom(filter_=None, sorts=None):
        raise ConnectionError("notion unreachable")

    monkeypatch.setattr(utils, "_query_db", boom)

    with pytest.raises(RuntimeError, match="read failed"):
        utils.db_find_job_by_url("https://example.com/jobs/1")


def test_db_find_job_by_url_returns_none_for_a_genuine_miss(monkeypatch):
    monkeypatch.setattr(utils, "_query_db", lambda filter_=None, sorts=None: [])
    assert utils.db_find_job_by_url("https://example.com/jobs/1") is None


def test_db_find_job_by_url_honours_exclude_page_id(monkeypatch):
    monkeypatch.setattr(utils, "_query_db", lambda filter_=None, sorts=None: [{"id": "self"}])
    assert utils.db_find_job_by_url("u", exclude_page_id="self") is None
    assert utils.db_find_job_by_url("u", exclude_page_id="other") == "self"


def test_db_find_job_by_url_short_circuits_on_blank_url(monkeypatch):
    def boom(filter_=None, sorts=None):
        raise AssertionError("should not query for a blank url")

    monkeypatch.setattr(utils, "_query_db", boom)
    assert utils.db_find_job_by_url("") is None


# ── 2b. _query_db is the choke point: the unguarded readers raise NotionReadError ──
# db_get_jobs() / db_get_ready_to_apply() never wrapped _query_db themselves, so a failed
# read used to propagate the raw Notion client exception (a traceback out of run.py's
# --retry-only / --evaluate / --stage 2-4 paths). Now every reader funnels through _query_db,
# which raises the typed NotionReadError.

def test_notion_read_error_is_a_runtime_error_subclass():
    """Subclassing RuntimeError is what keeps every existing `except RuntimeError` handler and
    `pytest.raises(RuntimeError, match='read failed')` test green after the retype."""
    assert issubclass(utils.NotionReadError, RuntimeError)


def test_query_db_wraps_a_read_failure_as_notion_read_error(monkeypatch):
    monkeypatch.setattr(utils, "NOTION_DB_ID", "db")

    class _Boom:
        class databases:
            @staticmethod
            def query(**kwargs):
                raise ConnectionError("notion unreachable")

    monkeypatch.setattr(utils, "_notion", lambda: _Boom)
    with pytest.raises(utils.NotionReadError, match="read failed"):
        utils._query_db()


def test_db_get_jobs_raises_notion_read_error_on_read_failure(monkeypatch):
    """Backs --retry-only (db_get_jobs('Retry')), --stage 2/3, --evaluate."""
    def boom(filter_=None, sorts=None):
        raise utils.NotionReadError("Notion read failed: 503")

    monkeypatch.setattr(utils, "_query_db", boom)
    with pytest.raises(utils.NotionReadError):
        utils.db_get_jobs("Reviewed")


def test_db_get_ready_to_apply_raises_notion_read_error_on_read_failure(monkeypatch):
    """Backs the --stage 4 ready digest."""
    def boom(filter_=None, sorts=None):
        raise utils.NotionReadError("Notion read failed: 503")

    monkeypatch.setattr(utils, "_query_db", boom)
    with pytest.raises(utils.NotionReadError):
        utils.db_get_ready_to_apply()


# ── 3. Scratch-note ingest tolerates the new raise ───────────────────────────

def test_scratch_ingest_leaves_row_unarchived_when_dedup_check_fails(monkeypatch):
    """db_find_job_by_url now raises. The scratch ingest must skip that URL and leave its row
    un-archived (the existing retry mechanism) rather than creating a row it can't prove isn't
    a duplicate — or dying and stranding every later row."""
    from scripts import stage1_scrape

    archived, created = [], []

    monkeypatch.setattr(stage1_scrape, "get_scratch_note_entries", lambda: [
        {"page_id": "s1", "url": "https://example.com/bad"},
        {"page_id": "s2", "url": "https://example.com/good"},
    ])

    def flaky_find(url, exclude_page_id=""):
        if url.endswith("/bad"):
            raise RuntimeError("db_find_job_by_url read failed")
        return None

    monkeypatch.setattr(stage1_scrape, "db_find_job_by_url", flaky_find)
    monkeypatch.setattr(stage1_scrape, "archive_scratch_note_entry", archived.append)
    monkeypatch.setattr(stage1_scrape, "db_add_interested_url",
                        lambda url: (created.append(url), "new-page")[1])

    added = stage1_scrape.ingest_from_scratch_note()

    assert added == 1
    assert created == ["https://example.com/good"]
    assert archived == ["s2"], "the un-checkable row should stay in the note for retry"


# ── 4. Transient-error classification ────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "Request timed out",
    "connection reset by peer",
    "server overloaded",
    "rate limit exceeded",
    "HTTP 429 Too Many Requests",
    "received status 503",
    "500 Internal Server Error",
])
def test_transient_errors_are_retried(msg):
    assert utils._is_transient_error(Exception(msg)) is True


@pytest.mark.parametrize("msg", [
    # Digits that merely contain a retryable status code — these are permanent failures the
    # bare-substring check turned into three pointless retries.
    "invalid_request_error: prompt is designed for 5000 tokens",
    "job id 4295001234 not found",
    "salary_range 150000-190000 failed validation",
    "authentication_error: invalid x-api-key",
])
def test_permanent_errors_are_not_retried(msg):
    assert utils._is_transient_error(Exception(msg)) is False


def test_call_with_retry_does_not_retry_a_permanent_error(monkeypatch):
    monkeypatch.setattr(utils.time, "sleep", lambda *_: None)
    attempts = []

    def call():
        attempts.append(1)
        raise Exception("invalid_request_error: prompt is 5000 tokens over the limit")

    with pytest.raises(utils.AIChatError):
        utils._call_with_retry(call)
    assert len(attempts) == 1, "a permanent error should not be retried"


# ── 5. ANTHROPIC_API_KEY is scoped to the claude_code call ───────────────────

def test_chat_claude_code_restores_anthropic_key_after_the_call(monkeypatch):
    """The key must be absent while the SDK spawns the CLI (or it bills metered), and present
    again afterwards — under hybrid tiering, metered and subscription calls interleave in one
    process, so leaving it popped mutates global state for every later call."""
    seen = {}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(utils, "_find_claude_cli", lambda: "claude")

    async def fake_sdk_text(prompt, system, model):
        seen["key_during_call"] = os.environ.get("ANTHROPIC_API_KEY")
        return "ok"

    monkeypatch.setattr(utils, "_sdk_text", fake_sdk_text)

    assert utils._chat_claude_code("p", "s", 100) == "ok"
    assert seen["key_during_call"] is None, "key leaked into the subscription call"
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-key", "key was not restored"


def test_chat_claude_code_restores_the_key_even_when_the_call_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(utils, "_find_claude_cli", lambda: "claude")

    async def boom(prompt, system, model):
        raise RuntimeError("sdk exploded")

    monkeypatch.setattr(utils, "_sdk_text", boom)

    with pytest.raises(RuntimeError, match="sdk exploded"):
        utils._chat_claude_code("p", "s", 100)
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-key"


def test_chat_claude_code_leaves_env_clean_when_no_key_was_set(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(utils, "_find_claude_cli", lambda: "claude")
    async def ok(prompt, system, model):
        return "ok"

    monkeypatch.setattr(utils, "_sdk_text", ok)

    assert utils._chat_claude_code("p", "s", 100) == "ok"
    assert "ANTHROPIC_API_KEY" not in os.environ


# ── 6. _active_provider tolerates a missing STAGE_AI_PROVIDER ────────────────

def test_active_provider_falls_back_when_stage_provider_is_absent(monkeypatch):
    """The hard `from config.settings import STAGE_AI_PROVIDER` turned a removed/renamed
    setting into an ImportError on every AI call."""
    monkeypatch.delattr(utils._settings, "STAGE_AI_PROVIDER", raising=False)
    monkeypatch.setattr(utils, "AI_PROVIDER", "claude")
    monkeypatch.setattr(utils._settings, "FAST_PROVIDER", "", raising=False)
    monkeypatch.setattr(utils._settings, "QUALITY_PROVIDER", "", raising=False)

    assert utils._active_provider(quality=False) == "claude"
    assert utils._active_provider(quality=True) == "claude"


def test_active_provider_still_honours_per_tier_overrides(monkeypatch):
    monkeypatch.setattr(utils, "AI_PROVIDER", "claude")
    monkeypatch.setattr(utils._settings, "FAST_PROVIDER", "claude", raising=False)
    monkeypatch.setattr(utils._settings, "QUALITY_PROVIDER", "claude_code", raising=False)

    assert utils._active_provider(quality=False) == "claude"
    assert utils._active_provider(quality=True) == "claude_code"


# ── 7. Interested intake tolerates the raise per-row, and partitions by host ──

def test_interested_intake_skips_only_the_row_whose_dedup_check_fails(monkeypatch):
    """Same contract as the scratch-note ingest: a failed dedup read skips that one row
    (it stays 'Interested' and is retried next run) rather than aborting the whole batch or
    promoting a row we can't prove isn't already tracked."""
    from scripts import stage1_scrape

    pages = [
        {"notion_page_id": "p1", "url": "https://example.com/bad",
         "title": "", "company": "", "location": "", "enrichment_attempts": 0},
        {"notion_page_id": "p2", "url": "https://example.com/good",
         "title": "", "company": "", "location": "", "enrichment_attempts": 0},
    ]
    monkeypatch.setattr(stage1_scrape, "get_notion_jobs_by_status", lambda s: pages)

    def flaky_find(url, exclude_page_id=""):
        if url.endswith("/bad"):
            raise RuntimeError("db_find_job_by_url read failed")
        return None

    enriched_urls = []

    def fake_enrich(url):
        enriched_urls.append(url)
        return {"title": "T", "company": "C", "location": "L", "description": "d" * 300}

    monkeypatch.setattr(stage1_scrape, "db_find_job_by_url", flaky_find)
    monkeypatch.setattr(stage1_scrape, "enrich_job_url", fake_enrich)
    monkeypatch.setattr(stage1_scrape, "score_jobs_batch", lambda jobs, resume: [
        {"url": j["url"], "score": 80, "scored": True, "missing_keywords": [],
         "sponsorship": "unknown", "company_type": "product"} for j in jobs
    ])
    promoted = []
    monkeypatch.setattr(stage1_scrape, "db_add_job_linked",
                        lambda job, pid, status="Scraped": promoted.append((pid, status)))
    monkeypatch.setattr(stage1_scrape, "AUTO_REVIEW_MIN_SCORE", 35)

    ingested = stage1_scrape.ingest_interested_from_notion("resume")

    assert ingested == 1, "one bad row aborted the whole batch"
    assert enriched_urls == ["https://example.com/good"]
    assert [pid for pid, _ in promoted] == ["p2"]


def test_interested_intake_partitions_linkedin_by_host_not_substring(monkeypatch):
    """A URL merely *containing* 'linkedin.com' (in a path or query) is not a LinkedIn job
    and must go to enrich_job_url(), not to the batched LinkedIn actor that can't enrich it."""
    from scripts import stage1_scrape

    pages = [
        {"notion_page_id": "p1", "url": "https://www.linkedin.com/jobs/view/123",
         "title": "", "company": "", "location": "", "enrichment_attempts": 0},
        {"notion_page_id": "p2", "url": "https://acme.com/careers?ref=linkedin.com",
         "title": "", "company": "", "location": "", "enrichment_attempts": 0},
    ]
    monkeypatch.setattr(stage1_scrape, "get_notion_jobs_by_status", lambda s: pages)
    monkeypatch.setattr(stage1_scrape, "db_find_job_by_url", lambda u, exclude_page_id="": None)

    to_actor, to_generic = [], []
    monkeypatch.setattr(stage1_scrape, "scrape_job_urls",
                        lambda urls: (to_actor.extend(urls), {})[1])
    monkeypatch.setattr(stage1_scrape, "enrich_job_url",
                        lambda url: (to_generic.append(url), None)[1])
    monkeypatch.setattr(stage1_scrape, "db_update_status", lambda *a, **k: None)
    monkeypatch.setattr(stage1_scrape, "MAX_ENRICHMENT_ATTEMPTS", 3)

    stage1_scrape.ingest_interested_from_notion("resume")

    assert to_actor == ["https://www.linkedin.com/jobs/view/123"]
    assert to_generic == ["https://acme.com/careers?ref=linkedin.com"]


# ── 8. --ingest reports a failed read cleanly instead of tracebacking ─────────

def test_ingest_routine_exits_nonzero_with_a_clean_message(monkeypatch, capsys):
    """The readers now raise. `run.py --ingest` must turn that into a message + non-zero
    exit, not a raw traceback -- and never into a silent 'Ingested 0 jobs'."""
    import run as run_module
    from scripts import stage1_scrape

    monkeypatch.setattr(stage1_scrape, "ingest_from_scratch_note", lambda: 0)

    def boom(resume):
        raise utils.NotionReadError("get_notion_jobs_by_status('Interested') read failed: 503")

    monkeypatch.setattr(stage1_scrape, "ingest_interested_from_notion", boom)
    monkeypatch.setattr("scripts.utils.load_resume", lambda: "resume")

    with pytest.raises(SystemExit) as excinfo:
        run_module.ingest_routine(object())

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Ingest aborted" in out
    assert "Ingested 0" not in out, "a failed read must never read as a successful empty run"
