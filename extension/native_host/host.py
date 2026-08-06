#!/usr/bin/env python3
"""
host.py — step-15j's native-messaging host: auto-starts the Stage 7 Layer 3 bridge
(`python run.py --serve`) so the extension never requires a manually-run terminal command.

Spec: docs/backlog/step-15-application-prefill-extension.md, increment 8 (standalone native
launch).

WHY THIS DOESN'T RELITIGATE "NEVER A DAEMON" (see the epic's security section)
    The bridge (scripts/autoapply_server.py) still runs only under an explicit `run.py --serve`
    invocation and still holds no state across restarts beyond the git-ignored token file it
    regenerates every time. What changes here is *who types the command* — Chrome only ever
    launches this host process in response to an explicit extension call
    (chrome.runtime.sendNativeMessage), itself only ever fired from an explicit human gesture
    (opening the side panel / a "Start bridge" click) — never a background timer, never on
    browser/OS startup. So the bridge stays session-scoped and human-triggered; only the
    keystrokes moved from a terminal to the extension UI.

WIRE PROTOCOL
    Chrome's native-messaging protocol: one message on stdin, one response on stdout, then this
    process exits — Chrome relaunches it per connectNative() call, so this is NOT a long-lived
    loop. Each message is a 4-byte little-endian length prefix followed by that many bytes of
    UTF-8 JSON.

ON {"action": "ensure_started", "port": <int>}
    1. GET http://127.0.0.1:<port>/health. If it answers, respond {"status":
       "already_running"} — no spawn, no token re-read (an already-running bridge's token is
       presumably already what the extension holds).
    2. Else spawn `python run.py --serve --port <port>` detached, cwd = repo root, with its own
       stdout/stderr redirected away from this process's stdio (must never pollute the NM
       channel — a stray print from the bridge would corrupt the length-prefixed stream Chrome
       is reading).
    3. Poll /health every ~0.3s up to ~8s total.
    4. On success, read config/extension_token.txt (the same TOKEN_PATH/write_token() path
       autoapply_server.py already writes — step-15a) and respond {"status": "started", "port":
       <int>, "token": "<str>"}.
    5. On timeout or any exception, respond {"status": "error", "message": "<str>"} — never
       raise past the wire-protocol write, since an unhandled exception here just looks like a
       hung host to Chrome, with no diagnostic surfaced anywhere the user can see it.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# extension/native_host/host.py -> repo root is two parents up.
ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = ROOT / "config" / "extension_token.txt"

DEFAULT_PORT = 8765
HEALTH_POLL_INTERVAL = 0.3
HEALTH_POLL_TIMEOUT = 8.0
HEALTH_CHECK_TIMEOUT = 1.0


# ── Wire protocol ──────────────────────────────────────────────────────────────

def read_message(stream=None) -> dict | None:
    """Read one length-prefixed JSON message, or None on EOF/a short read (Chrome closed the
    pipe without sending anything — happens on host shutdown, not an error)."""
    stream = stream if stream is not None else sys.stdin.buffer
    raw_length = stream.read(4)
    if not raw_length or len(raw_length) < 4:
        return None
    length = struct.unpack("<I", raw_length)[0]
    data = stream.read(length)
    return json.loads(data.decode("utf-8"))


def write_message(message: dict, stream=None) -> None:
    stream = stream if stream is not None else sys.stdout.buffer
    encoded = json.dumps(message).encode("utf-8")
    stream.write(struct.pack("<I", len(encoded)))
    stream.write(encoded)
    stream.flush()


# ── Bridge lifecycle ─────────────────────────────────────────────────────────

def read_token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def _health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=HEALTH_CHECK_TIMEOUT,
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _spawn_bridge(port: int) -> None:
    """Detached so this short-lived host process exiting (per the wire protocol above) doesn't
    take the bridge down with it. stdout/stderr go to DEVNULL — never this process's own stdio,
    which is the native-messaging channel itself."""
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "run.py", "--serve", "--port", str(port)],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **kwargs,
    )


def ensure_started(port: int, poll_interval: float = HEALTH_POLL_INTERVAL,
                    poll_timeout: float = HEALTH_POLL_TIMEOUT) -> dict:
    """Returns the response dict for an "ensure_started" request. Never raises — any failure
    anywhere in this path degrades to {"status": "error", "message": ...}."""
    try:
        if _health_ok(port):
            return {"status": "already_running"}

        _spawn_bridge(port)

        deadline = time.monotonic() + poll_timeout
        while time.monotonic() < deadline:
            if _health_ok(port):
                return {"status": "started", "port": port, "token": read_token()}
            time.sleep(poll_interval)
        return {"status": "error", "message": "bridge did not come up within the poll window"}
    except Exception as e:  # never let a spawn/poll failure escape as an unhandled exception
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


def handle_message(message: dict) -> dict:
    if not isinstance(message, dict) or message.get("action") != "ensure_started":
        return {"status": "error", "message": f"unknown action: {message!r}"}
    port = message.get("port") or DEFAULT_PORT
    return ensure_started(port)


def main() -> None:
    message = read_message()
    if message is None:
        return
    try:
        response = handle_message(message)
    except Exception as e:  # mirrors ensure_started's own contract at the outermost layer
        response = {"status": "error", "message": f"{type(e).__name__}: {e}"}
    write_message(response)


if __name__ == "__main__":
    main()
