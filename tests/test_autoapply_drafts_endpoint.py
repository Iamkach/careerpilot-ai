"""
POST /drafts — one AI-drafted answer per free-text question (step-15f).

Spec: spec/application-prefill-extension/, increment 4 (interactive draft
panel).
Exercises the wire contract via the real HTTP server, mirroring
tests/test_autoapply_jobs_ready_endpoint.py's pattern.

Conftest gotcha (see the story doc): drafting calls into scripts.autoapply, whose ai_chat is
bound at import time — patch_ai_chat(autoapply), not (autoapply_server), or this test would
silently hit a real/unmocked AI call path.
"""
import socket
import threading

import pytest
import requests

from scripts import autoapply, autoapply_server as srv

_DOM_PAYLOAD = {
    "title": "Apply",
    "questions": [
        {"label": "Why do you want to work here?*", "required": True,
         "fields": [{"name": "why_us", "domType": "textarea"}]},
    ],
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def bridge(tmp_path, monkeypatch, patch_notion_db, patch_ai_chat):
    token_path = tmp_path / "extension_token.txt"
    monkeypatch.setattr(srv, "TOKEN_PATH", token_path)
    monkeypatch.setattr(srv, "_candidate_pool_cache", None)
    monkeypatch.setattr(srv, "AUTOAPPLY_DRAFT_ESSAYS", True)
    db = patch_notion_db(srv)
    ai = patch_ai_chat(autoapply, response="I would love to work here because of the mission.")

    port = _free_port()
    httpd = srv.serve(port=port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", token_path, db, ai
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _auth_headers(token_path) -> dict:
    return {"Authorization": f"Bearer {token_path.read_text(encoding='utf-8').strip()}"}


def _seed_job_and_plan(base, token_path, db):
    page_id = db.seed(status="Resume Tailored", url="https://boards.greenhouse.io/acme/jobs/1",
                       title="Backend Engineer", company="Acme")
    resp = requests.post(
        f"{base}/plan",
        json={"live_url": "https://boards.greenhouse.io/acme/jobs/1", "dom": _DOM_PAYLOAD},
        headers=_auth_headers(token_path), timeout=5)
    return page_id, resp.json()["plan"]


def test_drafts_requires_token(bridge):
    base, _, db, _ai = bridge
    page_id = db.seed(status="Resume Tailored")
    resp = requests.post(f"{base}/drafts", json={"page_id": page_id, "plan": {"fields": []}},
                          timeout=5)
    assert resp.status_code == 401


def test_drafts_missing_page_id_returns_400(bridge):
    base, token_path, _db, _ai = bridge
    resp = requests.post(f"{base}/drafts", headers=_auth_headers(token_path),
                          json={"plan": {"fields": []}}, timeout=5)
    assert resp.status_code == 400


def test_drafts_missing_plan_returns_400(bridge):
    base, token_path, db, _ai = bridge
    page_id = db.seed(status="Resume Tailored")
    resp = requests.post(f"{base}/drafts", headers=_auth_headers(token_path),
                          json={"page_id": page_id}, timeout=5)
    assert resp.status_code == 400


def test_drafts_unknown_page_id_returns_404(bridge):
    base, token_path, _db, _ai = bridge
    resp = requests.post(f"{base}/drafts", headers=_auth_headers(token_path),
                          json={"page_id": "nope", "plan": {"fields": []}}, timeout=5)
    assert resp.status_code == 404


def test_drafts_happy_path_adds_draft_key_leaves_status_value_untouched(bridge):
    base, token_path, db, ai = bridge
    page_id, plan = _seed_job_and_plan(base, token_path, db)
    field = next(f for f in plan["fields"] if f["name"] == "why_us")
    assert field["status"] == "review_required"
    assert "draft" not in field

    resp = requests.post(f"{base}/drafts", headers=_auth_headers(token_path),
                          json={"page_id": page_id, "plan": plan}, timeout=5)

    assert resp.status_code == 200
    body = resp.json()
    assert body["drafted_count"] == 1
    drafted_field = next(f for f in body["plan"]["fields"] if f["name"] == "why_us")
    assert drafted_field["draft"] == "I would love to work here because of the mission."
    # Untouched — the fill loop's status == "ready" predicate keeps excluding this field.
    assert drafted_field["status"] == "review_required"
    assert drafted_field["value"] is None
    assert ai.calls  # confirms scripts.autoapply's ai_chat was the one actually invoked


def test_drafts_disabled_via_settings_is_a_clean_no_op(bridge, monkeypatch):
    base, token_path, db, _ai = bridge
    monkeypatch.setattr(srv, "AUTOAPPLY_DRAFT_ESSAYS", False)
    page_id, plan = _seed_job_and_plan(base, token_path, db)

    resp = requests.post(f"{base}/drafts", headers=_auth_headers(token_path),
                          json={"page_id": page_id, "plan": plan}, timeout=5)

    assert resp.status_code == 404
