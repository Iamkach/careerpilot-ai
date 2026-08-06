"""
extension/native_host/host.py — step-15j's native-messaging host.

Spec: spec/application-prefill-extension/, increment 8 (standalone native
launch).
Subprocess mocked throughout — no real Chrome/process spawn in CI, matching the story's own
"Automated" verification list.
"""
import io
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from extension.native_host import host


# ── Wire protocol ──────────────────────────────────────────────────────────────

def test_wire_protocol_round_trips_a_payload():
    buf = io.BytesIO()
    host.write_message({"status": "ok", "n": 3}, stream=buf)
    buf.seek(0)
    assert host.read_message(stream=buf) == {"status": "ok", "n": 3}


def test_wire_protocol_length_prefix_is_4_byte_little_endian():
    buf = io.BytesIO()
    host.write_message({"a": 1}, stream=buf)
    encoded = buf.getvalue()
    length = struct.unpack("<I", encoded[:4])[0]
    assert length == len(encoded) - 4


def test_read_message_returns_none_on_short_read():
    assert host.read_message(stream=io.BytesIO(b"")) is None
    assert host.read_message(stream=io.BytesIO(b"\x01\x00")) is None


# ── ensure_started() ─────────────────────────────────────────────────────────

def test_ensure_started_already_healthy_does_not_spawn(monkeypatch):
    monkeypatch.setattr(host, "_health_ok", lambda port: True)
    spawned = []
    monkeypatch.setattr(host, "_spawn_bridge", lambda port: spawned.append(port))

    result = host.ensure_started(8765)

    assert result == {"status": "already_running"}
    assert spawned == []


def test_ensure_started_spawns_once_when_unreachable_then_returns_token(monkeypatch, tmp_path):
    calls = {"health": 0, "spawn": 0}

    def fake_health(port):
        calls["health"] += 1
        return calls["health"] >= 3  # unhealthy twice, then healthy

    def fake_spawn(port):
        calls["spawn"] += 1

    token_path = tmp_path / "extension_token.txt"
    token_path.write_text("secret-token-123", encoding="utf-8")

    monkeypatch.setattr(host, "_health_ok", fake_health)
    monkeypatch.setattr(host, "_spawn_bridge", fake_spawn)
    monkeypatch.setattr(host, "TOKEN_PATH", token_path)

    result = host.ensure_started(8765, poll_interval=0)

    assert calls["spawn"] == 1
    assert result == {"status": "started", "port": 8765, "token": "secret-token-123"}


def test_ensure_started_spawns_with_expected_command_line_and_cwd(monkeypatch):
    monkeypatch.setattr(host, "_health_ok", lambda port: False)
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")

        class _Proc:
            pass
        return _Proc()

    monkeypatch.setattr(host.subprocess, "Popen", fake_popen)

    result = host.ensure_started(8765, poll_interval=0, poll_timeout=0)

    assert captured["cmd"] == [sys.executable, "run.py", "--serve", "--port", "8765"]
    assert captured["cwd"] == str(host.ROOT)
    assert result["status"] == "error"  # never turned healthy in this test — bounded, not hung


def test_ensure_started_never_turns_healthy_returns_bounded_error(monkeypatch):
    monkeypatch.setattr(host, "_health_ok", lambda port: False)
    monkeypatch.setattr(host, "_spawn_bridge", lambda port: None)

    result = host.ensure_started(8765, poll_interval=0, poll_timeout=0)

    assert result["status"] == "error"
    assert "message" in result


def test_ensure_started_catches_spawn_exception(monkeypatch):
    monkeypatch.setattr(host, "_health_ok", lambda port: False)

    def raising_spawn(port):
        raise RuntimeError("boom")

    monkeypatch.setattr(host, "_spawn_bridge", raising_spawn)

    result = host.ensure_started(8765, poll_interval=0, poll_timeout=0)

    assert result == {"status": "error", "message": "RuntimeError: boom"}


def test_ensure_started_catches_health_check_exception(monkeypatch):
    def raising_health(port):
        raise RuntimeError("network stack exploded")

    monkeypatch.setattr(host, "_health_ok", raising_health)

    result = host.ensure_started(8765, poll_interval=0, poll_timeout=0)

    assert result["status"] == "error"
    assert "network stack exploded" in result["message"]


# ── handle_message() / main() dispatch ───────────────────────────────────────

def test_handle_message_unknown_action_returns_error():
    result = host.handle_message({"action": "do_something_else"})
    assert result["status"] == "error"


def test_handle_message_ensure_started_defaults_port(monkeypatch):
    seen_ports = []
    monkeypatch.setattr(host, "ensure_started", lambda port, **kw: seen_ports.append(port) or {"status": "already_running"})

    host.handle_message({"action": "ensure_started"})

    assert seen_ports == [host.DEFAULT_PORT]


def test_handle_message_ensure_started_uses_given_port(monkeypatch):
    seen_ports = []
    monkeypatch.setattr(host, "ensure_started", lambda port, **kw: seen_ports.append(port) or {"status": "started"})

    host.handle_message({"action": "ensure_started", "port": 9999})

    assert seen_ports == [9999]
