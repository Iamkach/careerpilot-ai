"""
Phase 0 smoke test — proves the harness itself works (fixtures import real stage modules,
patch_ai_chat/patch_notion_db intercept calls correctly) before any Phase 1-3 test relies on
it. Not testing pipeline behavior/logic here — that starts in Phase 1.
"""
import json

from scripts import stage1_scrape


def test_patch_ai_chat_intercepts_claude_chat(patch_ai_chat):
    fake = patch_ai_chat(stage1_scrape, response='[{"url": "https://x", "score": 80}]')

    result = stage1_scrape.claude_chat("some prompt", system="some system")

    assert result == '[{"url": "https://x", "score": 80}]'
    assert len(fake.calls) == 1
    assert fake.calls[0]["prompt"] == "some prompt"
    assert fake.calls[0]["system"] == "some system"


def test_patch_ai_chat_queues_responses_in_order(patch_ai_chat):
    fake = patch_ai_chat(stage1_scrape, responses=["first", "second"])

    assert stage1_scrape.claude_chat("p1") == "first"
    assert stage1_scrape.claude_chat("p2") == "second"
    # queue exhausted — falls back to .response (empty string by default)
    assert stage1_scrape.claude_chat("p3") == ""


def test_patch_notion_db_add_and_read_back(patch_notion_db, sample_job):
    fake = patch_notion_db(stage1_scrape)

    page_id = stage1_scrape.db_add_job({**sample_job, "ats_score": 85})
    jobs = stage1_scrape.db_get_jobs(status="Scraped")

    assert len(jobs) == 1
    assert jobs[0]["page_id"] == page_id
    assert jobs[0]["url"] == sample_job["url"]
    assert jobs[0]["ats_score"] == 85


def test_patch_notion_db_seed_and_status_update(patch_notion_db):
    fake = patch_notion_db(stage1_scrape)
    page_id = fake.seed(status="Retry", title="Some Job", company="Acme", url="https://x",
                         scoring_attempts=1)

    stage1_scrape.db_update_status(page_id, "Scraped", {"ats_score": 90})

    jobs = stage1_scrape.db_get_jobs(status="Scraped")
    assert len(jobs) == 1
    assert jobs[0]["ats_score"] == 90


def test_sample_fixtures_are_well_formed(sample_resume, sample_job, sample_jobs):
    assert "Python" in sample_resume
    assert sample_job["url"].startswith("https://")
    assert len(sample_jobs) == 3
    assert len({j["url"] for j in sample_jobs}) == 3  # all distinct


def test_score_jobs_batch_end_to_end_with_fakes(patch_ai_chat, sample_jobs, sample_resume):
    """Exercises the real score_jobs_batch() plumbing (chunking included) against the fake
    AI backend — the same shape of test Phase 3 will build on, proving the harness supports it."""
    canned = [
        {"url": j["url"], "score": 70, "missing_keywords": ["AWS"], "sponsorship": "unknown",
         "company_type": "product"}
        for j in sample_jobs
    ]
    patch_ai_chat(stage1_scrape, response=json.dumps(canned))

    results = stage1_scrape.score_jobs_batch(sample_jobs, sample_resume)

    assert len(results) == 3
    assert all(r["scored"] for r in results)
    assert {r["url"] for r in results} == {j["url"] for j in sample_jobs}
