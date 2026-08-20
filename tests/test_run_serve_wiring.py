"""
run.py --serve / --port wiring (step-15a). Mirrors the --setup-profile wiring pattern:
the CLI flag routes to a thin routine that delegates to scripts/autoapply_server, without
actually starting a server in these tests.
"""
import sys

import pytest

import run as run_module


def test_serve_routine_delegates_to_autoapply_server(monkeypatch):
    calls = {}

    def fake_run_forever(port):
        calls["port"] = port

    monkeypatch.setattr("scripts.autoapply_server.run_forever", fake_run_forever)

    class Args:
        port = 9999

    run_module.serve_routine(Args())
    assert calls["port"] == 9999


def test_main_dispatches_serve_flag_before_stages(monkeypatch):
    calls = {}
    monkeypatch.setattr(run_module, "serve_routine", lambda args: calls.setdefault("served", args.port))
    monkeypatch.setattr(sys, "argv", ["run.py", "--serve", "--port", "8888"])

    with pytest.raises(SystemExit):
        run_module.main()

    assert calls["served"] == 8888


def test_default_port_is_8765(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--serve"])
    captured = {}
    monkeypatch.setattr(run_module, "serve_routine", lambda args: captured.setdefault("args", args))
    with pytest.raises(SystemExit):
        run_module.main()
    assert captured["args"].port == 8765
