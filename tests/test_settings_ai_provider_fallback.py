"""
Tests for config/settings.py's no-key subscription fallback.

When a tier (AI_PROVIDER / FAST_PROVIDER / QUALITY_PROVIDER) would resolve to "claude" but
ANTHROPIC_API_KEY isn't set, and the Claude Code subscription is usable (CLI on PATH or
CLAUDE_CODE_OAUTH_TOKEN set), that tier should silently fall back to "claude_code" instead of
every AI call failing with an auth error (this was the actual failure mode in the
2026-07-23 nightly run: FAST_PROVIDER=claude with no ANTHROPIC_API_KEY secret configured).
If neither a key nor a usable subscription is present, the raw value is left as "claude" so
`run.py --setup` still reports it missing (no silent behavior change when nothing is configured
at all).
"""
import config.settings as settings


def test_resolve_provider_falls_back_when_key_missing_and_cli_available(monkeypatch):
    monkeypatch.setattr(settings, "_ANTHROPIC_KEY_PRESENT", False)
    monkeypatch.setattr(settings, "_claude_code_available", lambda: True)
    assert settings._resolve_provider("claude") == "claude_code"


def test_resolve_provider_keeps_claude_when_key_present(monkeypatch):
    monkeypatch.setattr(settings, "_ANTHROPIC_KEY_PRESENT", True)
    monkeypatch.setattr(settings, "_claude_code_available", lambda: True)
    assert settings._resolve_provider("claude") == "claude"


def test_resolve_provider_leaves_claude_when_no_key_and_no_subscription(monkeypatch):
    """Neither auth path is usable — leave the value as "claude" so `run.py --setup` still
    surfaces the missing-key error, rather than silently swapping in an unusable provider."""
    monkeypatch.setattr(settings, "_ANTHROPIC_KEY_PRESENT", False)
    monkeypatch.setattr(settings, "_claude_code_available", lambda: False)
    assert settings._resolve_provider("claude") == "claude"


def test_resolve_provider_passes_through_non_claude_values(monkeypatch):
    monkeypatch.setattr(settings, "_ANTHROPIC_KEY_PRESENT", False)
    monkeypatch.setattr(settings, "_claude_code_available", lambda: True)
    assert settings._resolve_provider("gemini") == "gemini"
    assert settings._resolve_provider("claude_code") == "claude_code"


def test_claude_code_available_true_when_cli_on_path(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(settings.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    assert settings._claude_code_available() is True


def test_claude_code_available_true_when_oauth_token_set(monkeypatch):
    monkeypatch.setattr(settings.shutil, "which", lambda name: None)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token-value")
    assert settings._claude_code_available() is True


def test_claude_code_available_false_when_neither_present(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(settings.shutil, "which", lambda name: None)
    assert settings._claude_code_available() is False
