"""
Stage 7 Layer 3 bridge HTTP contract tests (scripts/autoapply_server.py).

Spec: spec/application-prefill-extension/, increments 0 (scaffold: /health,
      auth, CORS, bind), 1 (/plan, /resume/meta), and 3a (/resume bytes — this file's new cases).
      The pure-function behavior of identify_job()/_dom_to_schema()/build_plan_response() is
      covered in tests/test_autoapply_job_match.py; this file drives the real HTTP server over a
      loopback socket via `requests` for the wire contract only (auth, status codes, bytes).
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
    """Start a real bridge on a free port, with the token file redirected into tmp_path and
    the Notion layer faked so /plan and /resume/meta never touch a real Notion DB."""
    token_path = tmp_path / "extension_token.txt"
    monkeypatch.setattr(srv, "TOKEN_PATH", token_path)
    monkeypatch.setattr(srv, "_candidate_pool_cache", None)
    db = patch_notion_db(srv)

    port = _free_port()
    stub_routes = {"/stub-authed": (200, {"ok": True})}
    httpd = srv.serve(port=port, routes=stub_routes)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", token_path, db
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_health_returns_200_no_token(bridge):
    base, _, _db = bridge
    resp = requests.get(f"{base}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_unknown_route_returns_404(bridge):
    base, _, _db = bridge
    resp = requests.get(f"{base}/plan", timeout=5)
    assert resp.status_code == 404


def test_stub_authed_route_rejects_missing_token(bridge):
    base, _, _db = bridge
    resp = requests.get(f"{base}/stub-authed", timeout=5)
    assert resp.status_code == 401


def test_stub_authed_route_rejects_wrong_token(bridge):
    base, _, _db = bridge
    resp = requests.get(f"{base}/stub-authed",
                         headers={"Authorization": "Bearer wrong-token"}, timeout=5)
    assert resp.status_code == 401


def test_stub_authed_route_accepts_correct_token(bridge):
    base, token_path, _db = bridge
    token = token_path.read_text(encoding="utf-8").strip()
    resp = requests.get(f"{base}/stub-authed",
                         headers={"Authorization": f"Bearer {token}"}, timeout=5)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_bind_literal_is_loopback_not_all_interfaces():
    """Grep-level assertion: the source must bind the literal '127.0.0.1', never ''."""
    import inspect
    src = inspect.getsource(srv.serve)
    assert '"127.0.0.1"' in src
    assert '("", port)' not in src


def test_cors_echoes_request_origin_not_an_allowlist(bridge):
    base, _, _db = bridge
    origin = "chrome-extension://some-random-unpacked-id"
    resp = requests.get(f"{base}/health", headers={"Origin": origin}, timeout=5)
    assert resp.headers.get("Access-Control-Allow-Origin") == origin


def test_token_regenerated_across_invocations(tmp_path, monkeypatch):
    token_path = tmp_path / "extension_token.txt"
    monkeypatch.setattr(srv, "TOKEN_PATH", token_path)

    port1 = _free_port()
    httpd1 = srv.serve(port=port1)
    token1 = token_path.read_text(encoding="utf-8")
    httpd1.server_close()

    port2 = _free_port()
    httpd2 = srv.serve(port=port2)
    token2 = token_path.read_text(encoding="utf-8")
    httpd2.server_close()

    assert token1 != token2


def test_starting_twice_on_same_port_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "TOKEN_PATH", tmp_path / "extension_token.txt")
    port = _free_port()
    httpd = srv.serve(port=port)
    try:
        with pytest.raises(OSError):
            srv.serve(port=port)
    finally:
        httpd.server_close()


# ── POST /plan ────────────────────────────────────────────────────────────────

def _auth_headers(token_path) -> dict:
    return {"Authorization": f"Bearer {token_path.read_text(encoding='utf-8').strip()}"}


_DOM_PAYLOAD = {
    "title": "Backend Engineer",
    "questions": [
        {"label": "First Name", "required": True,
         "fields": [{"name": "first_name", "domType": "text"}]},
        {"label": "Resume/CV", "required": True,
         "fields": [{"name": "resume", "domType": "file"}]},
    ],
}


def test_plan_requires_token(bridge):
    base, _, _db = bridge
    resp = requests.post(f"{base}/plan", json={"live_url": "https://x.com/1"}, timeout=5)
    assert resp.status_code == 401


def test_plan_returns_200_with_plan_and_job_match(bridge):
    base, token_path, db = bridge
    db.seed(status="Resume Tailored", url="https://boards.greenhouse.io/acme/jobs/1")
    resp = requests.post(
        f"{base}/plan",
        json={"live_url": "https://boards.greenhouse.io/acme/jobs/1", "dom": _DOM_PAYLOAD},
        headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert "plan" in body and "job_match" in body and "channel" in body
    assert body["job_match"]["status"] == "matched"


def test_plan_invalid_json_body_returns_400(bridge):
    base, token_path, _db = bridge
    resp = requests.post(f"{base}/plan", data="not json",
                          headers={**_auth_headers(token_path),
                                    "Content-Type": "application/json"}, timeout=5)
    assert resp.status_code == 400


# ── GET /resume/meta ──────────────────────────────────────────────────────────

def test_resume_meta_requires_token(bridge):
    base, _, db = bridge
    page_id = db.seed(status="Resume Tailored", url="https://x.com/1")
    resp = requests.get(f"{base}/resume/meta", params={"page_id": page_id}, timeout=5)
    assert resp.status_code == 401


def test_resume_meta_missing_page_id_returns_400(bridge):
    base, token_path, _db = bridge
    resp = requests.get(f"{base}/resume/meta", headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 400


def test_resume_meta_unknown_page_id_returns_404(bridge):
    base, token_path, _db = bridge
    resp = requests.get(f"{base}/resume/meta", params={"page_id": "nope"},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 404


def test_resume_meta_known_job_returns_metadata_no_bytes(bridge, tmp_path):
    base, token_path, db = bridge
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"fake bytes")
    page_id = db.seed(status="Resume Tailored", url="https://x.com/1",
                       resume_link=resume.as_uri())
    resp = requests.get(f"{base}/resume/meta", params={"page_id": page_id},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "tailored.docx"
    assert body["size"] == len(b"fake bytes")
    assert "content" not in body


# ── GET /resume ───────────────────────────────────────────────────────────────

def test_resume_requires_token(bridge):
    base, _, db = bridge
    page_id = db.seed(status="Resume Tailored", url="https://x.com/1")
    resp = requests.get(f"{base}/resume", params={"page_id": page_id}, timeout=5)
    assert resp.status_code == 401


def test_resume_missing_page_id_returns_400(bridge):
    base, token_path, _db = bridge
    resp = requests.get(f"{base}/resume", headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 400


def test_resume_unknown_page_id_returns_404(bridge):
    base, token_path, _db = bridge
    resp = requests.get(f"{base}/resume", params={"page_id": "nope"},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 404


def test_resume_returns_bytes_for_known_job(bridge, tmp_path, monkeypatch):
    base, token_path, db = bridge
    monkeypatch.setattr(srv, "RESUMES_DIR", str(tmp_path))
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"fake docx bytes")
    page_id = db.seed(status="Resume Tailored", url="https://careers.acme.com/apply/1",
                       resume_link=resume.as_uri())

    resp = requests.get(f"{base}/resume", params={"page_id": page_id},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    assert resp.content == b"fake docx bytes"
    assert resp.headers["Content-Disposition"] == 'attachment; filename="tailored.docx"'
    assert "wordprocessingml" in resp.headers["Content-Type"]


def test_resume_403_on_readonly_channel(bridge, tmp_path, monkeypatch):
    """LinkedIn/Indeed get no bytes, enforced from the job's own stored URL (server-side,
    never trusting anything the client claims about the channel)."""
    base, token_path, db = bridge
    monkeypatch.setattr(srv, "RESUMES_DIR", str(tmp_path))
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"fake docx bytes")
    page_id = db.seed(status="Resume Tailored", url="https://www.linkedin.com/jobs/view/999",
                       resume_link=resume.as_uri())

    resp = requests.get(f"{base}/resume", params={"page_id": page_id},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 403


def test_resume_403_when_resolved_path_is_outside_resumes_dir(bridge, tmp_path, monkeypatch):
    """Hard containment check: resolve_tailored_resume() traces back to a user-editable Notion
    field, so any resolved path that lands outside RESUMES_DIR is refused rather than served."""
    resumes_dir = tmp_path / "resumes_root"
    resumes_dir.mkdir()
    monkeypatch.setattr(srv, "RESUMES_DIR", str(resumes_dir))

    outside = tmp_path / "elsewhere" / "tailored.docx"
    outside.parent.mkdir()
    outside.write_bytes(b"fake docx bytes")

    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", url="https://careers.acme.com/apply/1",
                       resume_link=outside.as_uri())

    resp = requests.get(f"{base}/resume", params={"page_id": page_id},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 403


def test_resume_pdf_fallback_when_accept_rejects_docx(bridge, tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "RESUMES_DIR", str(tmp_path))
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"fake docx bytes")
    pdf_path = tmp_path / "tailored.pdf"
    pdf_path.write_bytes(b"fake pdf bytes")
    monkeypatch.setattr(srv, "convert_docx_to_pdf", lambda path, out_dir=None: str(pdf_path))

    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", url="https://careers.acme.com/apply/1",
                       resume_link=resume.as_uri())

    resp = requests.get(f"{base}/resume", params={"page_id": page_id, "accept": ".pdf"},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 200
    assert resp.content == b"fake pdf bytes"
    assert resp.headers["Content-Type"] == "application/pdf"


def test_resume_conflict_when_pdf_conversion_fails(bridge, tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "RESUMES_DIR", str(tmp_path))
    resume = tmp_path / "tailored.docx"
    resume.write_bytes(b"fake docx bytes")
    monkeypatch.setattr(srv, "convert_docx_to_pdf", lambda path, out_dir=None: None)

    base, token_path, db = bridge
    page_id = db.seed(status="Resume Tailored", url="https://careers.acme.com/apply/1",
                       resume_link=resume.as_uri())

    resp = requests.get(f"{base}/resume", params={"page_id": page_id, "accept": ".pdf"},
                         headers=_auth_headers(token_path), timeout=5)
    assert resp.status_code == 409
