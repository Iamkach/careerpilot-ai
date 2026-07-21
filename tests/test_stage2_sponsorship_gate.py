"""
Phase 1 — unit tests for stage2_tailor._sponsorship_gate, using the Phase 0
patch_notion_db harness in place of the real Notion API.
"""
from scripts import stage2_tailor


def _job(company="Acme Corp", notes="", page_id="p1"):
    return {"page_id": page_id, "company": company, "title": "Backend Engineer", "notes": notes}


def test_unmatched_company_passes_through_untouched(monkeypatch, patch_notion_db):
    monkeypatch.setattr(stage2_tailor, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Restricted Co"])
    fake_db = patch_notion_db(stage2_tailor)

    jobs = [_job(company="Acme Corp")]
    cleared = stage2_tailor._sponsorship_gate(jobs)

    assert cleared == jobs
    assert fake_db.db_get_all_jobs() == []  # db_update_status was never called


def test_matched_company_without_marker_is_held_back(monkeypatch, patch_notion_db):
    monkeypatch.setattr(stage2_tailor, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Restricted Co"])
    monkeypatch.setattr(stage2_tailor, "SPONSORSHIP_CONFIRMED_MARKER", "sponsorship confirmed")
    fake_db = patch_notion_db(stage2_tailor)

    jobs = [_job(company="Restricted Co", notes="", page_id="p1")]
    cleared = stage2_tailor._sponsorship_gate(jobs)

    assert cleared == []
    rec = fake_db._pages["p1"]
    assert rec["status"] == "Human Review"
    assert "sponsorship confirmed" in rec["notes"].lower()  # guidance text mentions the marker


def test_matched_company_without_marker_appends_to_existing_notes(monkeypatch, patch_notion_db):
    monkeypatch.setattr(stage2_tailor, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Restricted Co"])
    monkeypatch.setattr(stage2_tailor, "SPONSORSHIP_CONFIRMED_MARKER", "sponsorship confirmed")
    fake_db = patch_notion_db(stage2_tailor)

    jobs = [_job(company="Restricted Co", notes="Pre-existing note.", page_id="p1")]
    stage2_tailor._sponsorship_gate(jobs)

    rec = fake_db._pages["p1"]
    assert rec["notes"].startswith("Pre-existing note.\n")


def test_matched_company_with_marker_is_released(monkeypatch, patch_notion_db):
    monkeypatch.setattr(stage2_tailor, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Restricted Co"])
    monkeypatch.setattr(stage2_tailor, "SPONSORSHIP_CONFIRMED_MARKER", "sponsorship confirmed")
    fake_db = patch_notion_db(stage2_tailor)

    jobs = [_job(company="Restricted Co", notes="Confirmed: sponsorship confirmed for this hire.")]
    cleared = stage2_tailor._sponsorship_gate(jobs)

    assert cleared == jobs
    assert fake_db._pages == {}  # released jobs are never written to Notion by the gate itself


def test_mixed_batch_only_restricted_companies_are_held_back(monkeypatch, patch_notion_db):
    # The real-world scenario the gate exists for: one stage-2 run processes many Reviewed
    # jobs at once, and only the restricted-company ones should ever be pulled aside — every
    # other job must tailor normally, unaffected by its neighbors in the same batch.
    monkeypatch.setattr(stage2_tailor, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Restricted Co"])
    monkeypatch.setattr(stage2_tailor, "SPONSORSHIP_CONFIRMED_MARKER", "sponsorship confirmed")
    fake_db = patch_notion_db(stage2_tailor)

    jobs = [
        _job(company="Acme Corp", page_id="p1"),
        _job(company="Restricted Co", page_id="p2"),
        _job(company="Beta Inc", page_id="p3"),
    ]
    cleared = stage2_tailor._sponsorship_gate(jobs)

    assert [j["page_id"] for j in cleared] == ["p1", "p3"]
    assert fake_db._pages["p2"]["status"] == "Human Review"
    assert "p1" not in fake_db._pages  # untouched jobs are never written to Notion at all
    assert "p3" not in fake_db._pages


def test_marker_match_is_case_insensitive(monkeypatch, patch_notion_db):
    monkeypatch.setattr(stage2_tailor, "RESTRICTED_SPONSORSHIP_COMPANIES", ["Restricted Co"])
    monkeypatch.setattr(stage2_tailor, "SPONSORSHIP_CONFIRMED_MARKER", "sponsorship confirmed")
    patch_notion_db(stage2_tailor)

    jobs = [_job(company="Restricted Co", notes="SPONSORSHIP CONFIRMED yesterday.")]
    assert stage2_tailor._sponsorship_gate(jobs) == jobs
