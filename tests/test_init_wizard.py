"""
Tests for run.py's `--init` onboarding flow.

Regression coverage for a real gap: `--init` provisioned Notion/Apify config and ran the
identity-profile wizard (name/roles/resume paths), but never actually invoked the Stage 7
application-profile wizard (work authorization, visa sponsorship, EEO, address) — even though
the careerpilot-ai skill doc already documented `init` as running both. A forker who only ran
`--init` was left without visa/work-auth answers captured anywhere, silently blocking `--stage 7`
later. These tests assert `_application_profile_wizard()` is wired into both `init_wizard()`
exit paths (fresh provision, and "keep existing tracker DB") and that it actually writes
`config/application_profile.json` when accepted.
"""
import json

import pytest

import run as run_module


def test_application_profile_wizard_writes_file_when_accepted(tmp_path, monkeypatch):
    """Accepting the prompt runs the same wizard as --setup-profile and saves its answers.

    `_application_profile_wizard()` imports `run_wizard`/`save_profile` fresh from
    scripts.autoapply_profile on every call, so patching those module attributes (rather than
    fighting run_wizard's `input_fn=input` default, bound at def-time) is what the real
    `--setup-profile` code path also exercises.
    """
    monkeypatch.setattr(run_module, "ROOT", tmp_path)
    profile_path = tmp_path / "config" / "application_profile.json"

    sentinel_profile = {"profile": {"first_name": "Ada"}, "presets": {}, "eeo": {}, "address": {}}
    monkeypatch.setattr("scripts.autoapply_profile.run_wizard", lambda: sentinel_profile)

    def fake_save(data, path=None):
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(data), encoding="utf-8")
        return profile_path

    monkeypatch.setattr("scripts.autoapply_profile.save_profile", fake_save)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")  # accept the "set up now?" prompt

    run_module._application_profile_wizard()

    assert profile_path.exists()
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    assert data["profile"]["first_name"] == "Ada"


def test_application_profile_wizard_skippable(tmp_path, monkeypatch, capsys):
    """Declining must not write a file or raise — mirrors _profile_wizard's skip behavior."""
    profile_path = tmp_path / "config" / "application_profile.json"
    monkeypatch.setattr("scripts.autoapply_profile.PROFILE_PATH", profile_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    run_module._application_profile_wizard()

    assert not profile_path.exists()
    assert "Skipped application-profile setup" in capsys.readouterr().out


def test_init_wizard_runs_application_profile_wizard_on_existing_db(tmp_path, monkeypatch):
    """The 'keep existing tracker DB, skip provisioning' exit path must still onboard the
    Stage 7 application profile — this is the branch the reported bug actually hit."""
    monkeypatch.setattr(run_module, "ROOT", tmp_path)
    monkeypatch.setenv("NOTION_API_KEY", "secret-token")
    monkeypatch.setenv("NOTION_DB_ID", "existingdbid")

    calls = []
    monkeypatch.setattr(run_module, "_profile_wizard", lambda env_path: calls.append("identity"))
    monkeypatch.setattr(run_module, "_application_profile_wizard", lambda: calls.append("application"))
    monkeypatch.setattr(run_module, "_sync_ci_secrets", lambda: calls.append("ci"))
    monkeypatch.setattr(run_module, "check_setup", lambda: calls.append("check"))

    responses = iter(["", "n"])  # keep API key as-is, then decline re-provisioning
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    result = run_module.init_wizard()

    assert result == 0
    assert calls == ["identity", "application", "ci", "check"]
