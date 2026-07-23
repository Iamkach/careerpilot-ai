"""
Tests for config/settings.py's identity-profile overlay (Step 11 Phase 2, item 2a).

Mirrors the contract of the existing application_profile.json overlay: the checked-in literals
are generic placeholders, a git-ignored config/profile.json overrides them, and a missing or
corrupt file is a silent no-op so the generic defaults stand. Two layers are covered:
  - _load_profile() directly (valid / missing / corrupt file), the reusable helper, and
  - the module-level constants (YOUR_NAME, TARGET_ROLES, AI_PROVIDER, RESUME_TEMPLATE_PATH, …)
    actually wiring through _profile.get(), verified by reloading the module with a real
    config/profile.json in place (backed up/restored so the test never clobbers a real one).
"""
import importlib
import json
from pathlib import Path

import config.settings as settings


# ── _load_profile() helper contract ───────────────────────────────────────────

def test_load_profile_reads_valid_json(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"name": "Fork User", "ai_provider": "gemini"}), encoding="utf-8")
    assert settings._load_profile(path=p) == {"name": "Fork User", "ai_provider": "gemini"}


def test_load_profile_missing_file_returns_empty(tmp_path):
    assert settings._load_profile(path=tmp_path / "does_not_exist.json") == {}


def test_load_profile_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert settings._load_profile(path=p) == {}


def test_load_profile_non_dict_returns_empty(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(["a", "list", "not", "a", "dict"]), encoding="utf-8")
    assert settings._load_profile(path=p) == {}


# ── module constants wire through the overlay ─────────────────────────────────

def test_constants_default_to_generic_placeholders():
    """With no config/profile.json present (git-ignored, absent on a fork), the checked-in
    defaults are the generic placeholders — no owner identity."""
    real = Path(settings.__file__).resolve().parent / "profile.json"
    if real.exists():
        # A local dev machine may have a real profile.json — this assertion only holds on a
        # clean checkout, so skip rather than fail against the owner's local overlay.
        import pytest
        pytest.skip("config/profile.json present locally; generic-default assertion N/A")
    assert settings.YOUR_NAME == "Your Name"
    assert settings.YOUR_EMAIL == "you@example.com"
    assert settings.AI_PROVIDER == "claude"
    assert settings.RESUME_TEMPLATE_PATH == "config/resume.docx"
    assert "Achyuth" not in settings.YOUR_NAME  # no owner identity in tracked defaults


def test_profile_json_overrides_defaults_on_reload():
    """A real config/profile.json overlays every identity constant. Backed up/restored so the
    test never clobbers a developer's local overlay."""
    real = Path(settings.__file__).resolve().parent / "profile.json"
    backup = real.read_bytes() if real.exists() else None
    try:
        real.write_text(json.dumps({
            "name":                 "Fork User",
            "email":                "fork@example.com",
            "bio":                  "A forker bio.",
            "target_roles":         ["Role A", "Role B"],
            "target_companies":     ["Co A"],
            "resume_path":          "config/my_resume.txt",
            "resume_template_path": "config/my_resume.docx",
            "ai_provider":          "gemini",
        }), encoding="utf-8")
        importlib.reload(settings)

        assert settings.YOUR_NAME == "Fork User"
        assert settings.YOUR_EMAIL == "fork@example.com"
        assert settings.YOUR_BIO == "A forker bio."
        assert settings.TARGET_ROLES == ["Role A", "Role B"]
        assert settings.TARGET_COMPANIES == ["Co A"]
        assert settings.RESUME_PATH == "config/my_resume.txt"
        assert settings.RESUME_TEMPLATE_PATH == "config/my_resume.docx"
        assert settings.AI_PROVIDER == "gemini"
    finally:
        if backup is None:
            real.unlink(missing_ok=True)
        else:
            real.write_bytes(backup)
        importlib.reload(settings)  # restore module state for any later tests
