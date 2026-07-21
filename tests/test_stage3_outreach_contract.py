"""
Phase 3b — mocked AI-flow contract tests for scripts/stage3_outreach.py's drafting path,
seeded from Phase 3a's real-model recordings (tests/fixtures/recorded_ai_responses/).

Tests the plumbing: cold-email/InMail batch-to-single fallback, InMail's subject/body
truncation boundaries, and a documented (not fixed) characterization test for the cold-email
single fallback's ad-hoc JSON-fence stripping — not AI judgment quality.
"""
import json

from scripts import stage3_outreach
from tests.conftest import load_recorded, make_recorded_jobs


def test_draft_cold_emails_batch_replays_recorded(patch_ai_chat):
    jobs = make_recorded_jobs(5)
    patch_ai_chat(stage3_outreach, response=load_recorded("stage3_outreach", "cold_email_batch_5"))

    results = stage3_outreach.draft_cold_emails_batch(jobs, "my background")

    assert len(results) == 5
    assert [r["company"] for r in results] == [j["company"] for j in jobs]
    for r in results:
        assert r["subject"]
        assert r["body"]


def test_draft_cold_emails_batch_falls_back_to_per_job_on_malformed_response(patch_ai_chat):
    """A batch response that isn't parseable JSON must not lose every job — falls back to
    _draft_cold_email_single per job instead."""
    jobs = make_recorded_jobs(2)
    fake = patch_ai_chat(stage3_outreach)
    # First call (the batch attempt) returns garbage; the two fallback single calls succeed.
    fake.set_responses([
        "Sorry, I can't do that.",
        '{"subject": "Hi Acme", "body": "Body one"}',
        '{"subject": "Hi Beta", "body": "Body two"}',
    ])

    results = stage3_outreach.draft_cold_emails_batch(jobs, "my background")

    assert len(fake.calls) == 3  # 1 failed batch call + 2 per-job fallback calls
    assert len(results) == 2
    assert results[0] == {"company": "Acme Corp", "subject": "Hi Acme", "body": "Body one"}
    assert results[1] == {"company": "Beta Inc", "subject": "Hi Beta", "body": "Body two"}


def test_draft_cold_emails_batch_does_not_amplify_on_hard_batch_failure(patch_ai_chat):
    """PR #11 issue 11: when the batch AI call itself raises (e.g. AIChatError after ai_chat's
    own 3-attempt retry budget is exhausted — a real outage), draft_cold_emails_batch must NOT
    fall back to N individually-retried calls, which would turn 1 failed call into up to 3N
    more against an already-failing service. It should make exactly one call, log the failure,
    and return a "not drafted this run" placeholder per job instead."""
    jobs = make_recorded_jobs(3)
    fake = patch_ai_chat(stage3_outreach)
    fake.raises = RuntimeError("AI call failed after retries: connection timeout")

    results = stage3_outreach.draft_cold_emails_batch(jobs, "my background")

    assert len(fake.calls) == 1  # no per-job amplification
    assert len(results) == 3
    for job, r in zip(jobs, results):
        assert r["company"] == job["company"]
        assert r["subject"] == ""
        assert r["body"] == ""


def test_draft_cold_emails_batch_detects_positional_misalignment_and_falls_back(patch_ai_chat):
    """If the model's JSON array order doesn't match the requested job order (e.g. a shifted
    response), draft_cold_emails_batch must not blindly trust position — it validates each
    entry's own "company" field and, since both companies here are unique in the batch, can
    still resolve the shift via a company-keyed lookup instead of cross-assigning."""
    jobs = make_recorded_jobs(2)  # Acme Corp, Beta Inc — both unique companies
    fake = patch_ai_chat(stage3_outreach)
    # Beta Inc's entry comes first — data[0] would wrongly land on jobs[0] (Acme Corp) under
    # pure positional trust.
    fake.set_response(json.dumps([
        {"company": jobs[1]["company"], "subject": "Hi Beta", "body": "Body for Beta"},
        {"company": jobs[0]["company"], "subject": "Hi Acme", "body": "Body for Acme"},
    ]))

    results = stage3_outreach.draft_cold_emails_batch(jobs, "my background")

    by_company = {r["company"]: r for r in results}
    assert by_company[jobs[0]["company"]]["body"] == "Body for Acme"
    assert by_company[jobs[1]["company"]]["body"] == "Body for Beta"


def test_draft_cold_emails_batch_same_company_ambiguous_falls_back_per_job(patch_ai_chat):
    """Two jobs at the same company, with a batch response that matches neither by position
    nor by company (so the company-keyed fallback is correctly refused as ambiguous), must
    fall back to a per-job call for each rather than cross-assigning the same wrong entry."""
    jobs = [
        {**make_recorded_jobs(1)[0], "company": "Acme Corp", "title": "Backend Engineer"},
        {**make_recorded_jobs(1)[0], "company": "Acme Corp", "title": "Frontend Engineer"},
    ]
    fake = patch_ai_chat(stage3_outreach)
    fake.set_responses([
        json.dumps([
            {"company": "Zeta Corp", "subject": "s1", "body": "b1"},
            {"company": "Zeta Corp", "subject": "s2", "body": "b2"},
        ]),
        '{"subject": "Hi Backend", "body": "Backend body"}',
        '{"subject": "Hi Frontend", "body": "Frontend body"}',
    ])

    results = stage3_outreach.draft_cold_emails_batch(jobs, "my background")

    assert len(fake.calls) == 3  # 1 batch call + 2 per-job fallback calls
    assert results[0]["body"] == "Backend body"
    assert results[1]["body"] == "Frontend body"


def test_run_same_company_jobs_do_not_cross_assign_emails(monkeypatch, tmp_path):
    """run()'s cold-email path must attach each drafted email to its own job even when two
    jobs share a company — a company-keyed dict re-lookup would let the second job's entry
    silently overwrite the first's in the lookup table."""
    jobs = [
        {"page_id": "p1", "company": "Acme Corp", "title": "Backend Engineer", "url": "https://x/1"},
        {"page_id": "p2", "company": "Acme Corp", "title": "Frontend Engineer", "url": "https://x/2"},
    ]
    monkeypatch.setattr(stage3_outreach, "db_get_ready_to_apply", lambda: jobs)
    monkeypatch.setattr(stage3_outreach, "OUTREACH_DIR", str(tmp_path))
    monkeypatch.setattr(
        stage3_outreach, "draft_cold_emails_batch",
        lambda js, bio: [
            {"company": j["company"], "subject": f"subj-{j['title']}", "body": f"body-for-{j['title']}"}
            for j in js
        ],
    )

    stage3_outreach.run(no_confirm=True)

    files = sorted(tmp_path.glob("*.txt"))
    assert len(files) == 2
    backend_file = next(f for f in files if "Backend_Engineer" in f.name)
    frontend_file = next(f for f in files if "Frontend_Engineer" in f.name)
    assert "body-for-Backend Engineer" in backend_file.read_text()
    assert "body-for-Frontend Engineer" in frontend_file.read_text()


def test_run_skips_writing_a_draft_when_batch_call_fails(monkeypatch, tmp_path):
    """run()'s cold-email path must not write a blank draft file or offer to mark a job
    'Outreach Sent' when draft_cold_emails_batch()'s outage placeholder (empty subject/body)
    comes back for a job — it should log and leave the job for the next run to retry."""
    jobs = [
        {"page_id": "p1", "company": "Acme Corp", "title": "Backend Engineer", "url": "https://x/1"},
    ]
    monkeypatch.setattr(stage3_outreach, "db_get_ready_to_apply", lambda: jobs)
    monkeypatch.setattr(stage3_outreach, "OUTREACH_DIR", str(tmp_path))
    monkeypatch.setattr(
        stage3_outreach, "draft_cold_emails_batch",
        lambda js, bio: [stage3_outreach._draft_failed(j) for j in js],
    )

    stage3_outreach.run(no_confirm=True)

    files = sorted(tmp_path.glob("*.txt"))
    assert files == []


def test_draft_inmail_batch_replays_recorded(patch_ai_chat):
    jobs = make_recorded_jobs(5)
    for j in jobs:
        j["ats_score"] = 85
    patch_ai_chat(stage3_outreach, response=load_recorded("stage3_outreach", "inmail_batch_5"))

    results = stage3_outreach.draft_inmail_batch(jobs, "my background")

    assert len(results) == 5
    for r in results:
        assert len(r["subject"]) <= 200
        assert len(r["body"]) <= 1900
        assert r["subject"] and r["body"]


def test_draft_inmail_batch_truncates_oversized_subject_and_body(patch_ai_chat):
    """LinkedIn InMail hard limits: subject <= 200 chars, body <= 1900 chars. A model reply
    that exceeds either must be truncated, not passed through or dropped."""
    import json
    jobs = make_recorded_jobs(1)
    oversized_subject = "S" * 250
    oversized_body = "B" * 2000
    canned = [{"company": jobs[0]["company"], "subject": oversized_subject, "body": oversized_body}]
    patch_ai_chat(stage3_outreach, response=json.dumps(canned))

    results = stage3_outreach.draft_inmail_batch(jobs, "my background")

    assert len(results[0]["subject"]) == 200
    assert len(results[0]["body"]) == 1900
    assert results[0]["subject"] == oversized_subject[:200]
    assert results[0]["body"] == oversized_body[:1900]


def test_draft_inmail_batch_falls_back_to_per_job_on_malformed_response(patch_ai_chat):
    jobs = make_recorded_jobs(1)
    fake = patch_ai_chat(stage3_outreach)
    fake.set_responses([
        "not json",
        '{"subject": "Hi", "body": "Short body"}',
    ])

    results = stage3_outreach.draft_inmail_batch(jobs, "my background")

    assert len(fake.calls) == 2
    assert results == [{"company": jobs[0]["company"], "subject": "Hi", "body": "Short body"}]


# ── Characterization test: cold-email single fallback's ad-hoc JSON stripping ──────────────

def test_run_inmail_same_company_jobs_do_not_cross_assign(monkeypatch, tmp_path):
    """run_inmail() must attach each drafted InMail to its own job even when two eligible
    jobs share a company — same company-keyed-dict collision pattern as the cold-email path."""
    jobs = [
        {"page_id": "p1", "company": "Acme Corp", "title": "Backend Engineer",
         "url": "https://x/1", "ats_score": 90},
        {"page_id": "p2", "company": "Acme Corp", "title": "Frontend Engineer",
         "url": "https://x/2", "ats_score": 90},
    ]
    monkeypatch.setattr(stage3_outreach, "db_get_ready_to_apply", lambda: jobs)
    monkeypatch.setattr(stage3_outreach, "INMAIL_DIR", str(tmp_path))
    monkeypatch.setattr(
        stage3_outreach, "draft_inmail_batch",
        lambda js, bio: [
            {"company": j["company"], "subject": f"subj-{j['title']}", "body": f"body-for-{j['title']}"}
            for j in js
        ],
    )
    import config.settings as settings
    monkeypatch.setattr(settings, "INMAIL_ATS_THRESHOLD", 0, raising=False)

    stage3_outreach.run_inmail(no_confirm=True)

    files = sorted(tmp_path.glob("*.txt"))
    assert len(files) == 2
    backend_file = next(f for f in files if "Backend_Engineer" in f.name)
    frontend_file = next(f for f in files if "Frontend_Engineer" in f.name)
    assert "body-for-Backend Engineer" in backend_file.read_text()
    assert "body-for-Frontend Engineer" in frontend_file.read_text()


def test_cold_email_single_fallback_recovers_json_from_prose_preamble(patch_ai_chat):
    """_draft_cold_email_single now parses its response with parse_json_response (formerly
    an ad-hoc raw.strip().strip("```json").strip("```") that could not recover embedded JSON
    from a response with a prose preamble — documented gap in
    docs/backlog/step-9-evals-testing.md's non-goals, now fixed). A response with text before
    the JSON object should have that JSON recovered rather than leaking the preamble into
    what would be sent to a real hiring contact."""
    job = make_recorded_jobs(1)[0]
    raw = 'Sure, here\'s the email:\n\n{"subject": "Hi there", "body": "Great opportunity"}'
    patch_ai_chat(stage3_outreach, response=raw)

    result = stage3_outreach._draft_cold_email_single(job, "my background")

    assert result == {"company": job["company"], "subject": "Hi there", "body": "Great opportunity"}


def test_cold_email_single_fallback_handles_a_clean_fenced_response(patch_ai_chat):
    """For contrast: a response that's ONLY a ```json fenced object (no prose) does parse
    correctly today — the ad-hoc stripping happens to work when there's nothing surrounding
    the fence, which is why this gap has stayed latent."""
    job = make_recorded_jobs(1)[0]
    raw = '```json\n{"subject": "Hi there", "body": "Great opportunity"}\n```'
    patch_ai_chat(stage3_outreach, response=raw)

    result = stage3_outreach._draft_cold_email_single(job, "my background")

    assert result == {"company": job["company"], "subject": "Hi there", "body": "Great opportunity"}
