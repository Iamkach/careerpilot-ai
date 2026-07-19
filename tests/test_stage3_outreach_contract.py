"""
Phase 3b — mocked AI-flow contract tests for scripts/stage3_outreach.py's drafting path,
seeded from Phase 3a's real-model recordings (tests/fixtures/recorded_ai_responses/).

Tests the plumbing: cold-email/InMail batch-to-single fallback, InMail's subject/body
truncation boundaries, and a documented (not fixed) characterization test for the cold-email
single fallback's ad-hoc JSON-fence stripping — not AI judgment quality.
"""
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
