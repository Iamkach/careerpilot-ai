"""
GET /jobs/ready — the side panel's job-list launcher (step-15h).

Spec: spec/application-prefill-extension/, increment 6 (job list + launcher).
Wraps db_get_ready_to_apply() verbatim (Status = 'Resume Tailored', empty Date Applied, score
desc) — this file exercises the wire contract (auth, shape, read-only) via the real HTTP server,
mirroring tests/test_autoapply_server.py's pattern.
"""
import socket
import threading

import pytest
import requests

from scripts import autoapply_server as srv


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


def test_jobs_ready_requires_token(bridge):
    base, _, _db = bridge
    resp = requests.get(f"{base}/jobs/ready", timeout=5)
    assert resp.status_code == 401


def test_jobs_ready_returns_resume_tailored_rows_sorted_by_score_desc(bridge):
    base, token_path, db = bridge
    db.seed(status="Resume Tailored", url="https://boards.greenhouse.io/acme/jobs/1",
            title="Backend Engineer", company="Acme", ats_score=70)
    db.seed(status="Resume Tailored", url="https://boards.greenhouse.io/acme/jobs/2",
            title="Platform Engineer", company="Acme", ats_score=90)
    # Not ready: wrong status, and applied-already should be excluded by db_get_ready_to_apply().
    db.seed(status="Reviewed", url="https://boards.greenhouse.io/acme/jobs/3",
            title="Should not appear", company="Acme", ats_score=99)

    resp = requests.get(f"{base}/jobs/ready", headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert [j["title"] for j in jobs] == ["Platform Engineer", "Backend Engineer"]
    assert [j["score"] for j in jobs] == [90, 70]


def test_jobs_ready_row_shape_has_page_id_and_url(bridge):
    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", url="https://boards.greenhouse.io/acme/jobs/1",
                       title="Backend Engineer", company="Acme", ats_score=70)

    resp = requests.get(f"{base}/jobs/ready", headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    job = resp.json()["jobs"][0]
    assert job["page_id"] == page_id
    assert job["url"] == "https://boards.greenhouse.io/acme/jobs/1"
    assert job["company"] == "Acme"


def test_jobs_ready_empty_when_none_tailored(bridge):
    base, token_path, _db = bridge
    resp = requests.get(f"{base}/jobs/ready", headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []
