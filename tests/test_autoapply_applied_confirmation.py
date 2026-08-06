"""
POST /confirm-applied — the only Notion status write the browser extension makes (step-15g).

Spec: spec/application-prefill-extension/, increment 5 (confirm-applied).
Exercises the wire contract (auth, validation, the actual write) via the real HTTP server,
mirroring tests/test_autoapply_jobs_ready_endpoint.py's pattern. The `Applied`-invariant
constants (HUMAN_CONFIRMED_STATUS/CONFIRMABLE_STATUSES vs. WRITABLE_STATUSES) are checked as
plain set assertions, no server needed.
"""
import socket
import threading

import pytest
import requests

from scripts import autoapply_server as srv
from scripts.autoapply import WRITABLE_STATUSES


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def bridge(tmp_path, monkeypatch, patch_notion_db):
    token_path = tmp_path / "extension_token.txt"
    monkeypatch.setattr(srv, "TOKEN_PATH", token_path)
    monkeypatch.setattr(srv, "_candidate_pool_cache", None)
    db = patch_notion_db(srv)
    db.known_statuses = WRITABLE_STATUSES | {"Resume Tailored", "Applied"}

    port = _free_port()
    httpd = srv.serve(port=port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", token_path, db
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _auth_headers(token_path) -> dict:
    return {"Authorization": f"Bearer {token_path.read_text(encoding='utf-8').strip()}"}


# ── Invariant: HUMAN_CONFIRMED_STATUS/CONFIRMABLE_STATUSES never overlap WRITABLE_STATUSES ──

def test_confirmable_statuses_disjoint_from_writable_statuses():
    assert srv.CONFIRMABLE_STATUSES & WRITABLE_STATUSES == set()


def test_human_confirmed_status_is_applied():
    assert srv.HUMAN_CONFIRMED_STATUS == "Applied"
    assert srv.HUMAN_CONFIRMED_STATUS in srv.CONFIRMABLE_STATUSES


# ── Wire contract ──────────────────────────────────────────────────────────────

def test_confirm_applied_requires_token(bridge):
    base, _, _db = bridge
    resp = requests.post(f"{base}/confirm-applied",
                          json={"page_id": "x", "confirmed_by": "human"}, timeout=5)
    assert resp.status_code == 401


def test_confirm_applied_missing_confirmed_by_rejected(bridge):
    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", company="Acme")
    resp = requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                          json={"page_id": page_id}, timeout=5)
    assert resp.status_code == 400
    assert db._pages[page_id]["status"] == "Resume Tailored"  # untouched


def test_confirm_applied_wrong_confirmed_by_rejected(bridge):
    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", company="Acme")
    resp = requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                          json={"page_id": page_id, "confirmed_by": "automation"}, timeout=5)
    assert resp.status_code == 400
    assert db._pages[page_id]["status"] == "Resume Tailored"


def test_confirm_applied_batch_page_id_rejected(bridge):
    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", company="Acme")
    resp = requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                          json={"page_id": [page_id], "confirmed_by": "human"}, timeout=5)
    assert resp.status_code == 400
    assert db._pages[page_id]["status"] == "Resume Tailored"


def test_confirm_applied_missing_page_id_rejected(bridge):
    base, token_path, _db = bridge
    resp = requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                          json={"confirmed_by": "human"}, timeout=5)
    assert resp.status_code == 400


def test_confirm_applied_happy_path_sets_applied_and_audit_log(bridge):
    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", company="Acme", title="Backend Engineer")

    resp = requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                          json={"page_id": page_id, "confirmed_by": "human"}, timeout=5)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "page_id": page_id}
    rec = db._pages[page_id]
    assert rec["status"] == "Applied"
    assert rec["date_applied"]
    assert "human-confirmed via extension" in rec["application_log"]


def test_confirm_applied_other_pages_untouched(bridge):
    base, token_path, db = bridge
    target = db.seed(status="Resume Tailored", company="Acme")
    other = db.seed(status="Resume Tailored", company="Beta")

    requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                  json={"page_id": target, "confirmed_by": "human"}, timeout=5)

    assert db._pages[target]["status"] == "Applied"
    assert db._pages[other]["status"] == "Resume Tailored"


def test_confirm_applied_reports_failure_when_notion_drops_the_status(bridge):
    """Mirrors test_autoapply_notion.py's reproduction of a Status select missing the option —
    Notion silently keeps the old status, and this must be reported as a failure, not a
    silent 200, so the human doesn't walk away believing the tracker updated."""
    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", company="Acme")
    db.known_statuses = WRITABLE_STATUSES | {"Resume Tailored"}  # "Applied" NOT registered

    resp = requests.post(f"{base}/confirm-applied", headers=_auth_headers(token_path),
                          json={"page_id": page_id, "confirmed_by": "human"}, timeout=5)

    assert resp.status_code != 200
    assert db._pages[page_id]["status"] == "Resume Tailored"
