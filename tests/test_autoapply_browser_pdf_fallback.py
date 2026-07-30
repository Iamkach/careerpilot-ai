"""
Step 10 residual gap #2 — scripts/autoapply_browser._resolve_upload_path()'s docx->PDF
fallback. Unlike tests/test_autoapply_browser.py, these don't touch Playwright/Chromium at
all (they exercise the pure resolution logic against a fake locator), so they run in the
default fast suite rather than under `pytest -m browser`.
"""
from scripts import autoapply_browser


class _FakeLocator:
    def __init__(self, accept: str):
        self._accept = accept

    def get_attribute(self, name):
        return self._accept if name == "accept" else None


def test_resolve_upload_path_returns_docx_as_is_when_form_accepts_it():
    loc = _FakeLocator(".docx,.doc")
    assert autoapply_browser._resolve_upload_path(loc, "resume.docx") == "resume.docx"


def test_resolve_upload_path_falls_back_to_converted_pdf_when_form_is_pdf_only(monkeypatch):
    loc = _FakeLocator(".pdf")
    import scripts.render_docx as render_docx
    monkeypatch.setattr(render_docx, "convert_docx_to_pdf",
                         lambda path, out_dir=None: path.replace(".docx", ".pdf"))

    result = autoapply_browser._resolve_upload_path(loc, "resume.docx")
    assert result == "resume.pdf"


def test_resolve_upload_path_returns_none_when_conversion_unavailable(monkeypatch):
    loc = _FakeLocator(".pdf")
    import scripts.render_docx as render_docx
    monkeypatch.setattr(render_docx, "convert_docx_to_pdf", lambda path, out_dir=None: None)

    assert autoapply_browser._resolve_upload_path(loc, "resume.docx") is None
