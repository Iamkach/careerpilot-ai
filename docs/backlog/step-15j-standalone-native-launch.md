# Step 15j — Standalone bridge auto-launch (Layer 3, increment 8)

**Status:** queued, not started (2026-08-01). Size **M**. Depends on
[step-15a](step-15a-serve-bridge-scaffold.md) (needs `run.py --serve`, the token file, `GET
/health`) and [step-15c](step-15c-extension-readonly-overlay.md) (needs `options.html`/the panel
shell this story edits). Independent of [step-15d](step-15d-resume-attach.md)–
[step-15i](step-15i-multi-session-state.md) — those extend what the bridge does; this story only
changes how it gets started. Tenth of ten sub-stories split from
[step-15-application-prefill-extension.md](step-15-application-prefill-extension.md) (read it
first).

## Goal

Remove the standing manual step where the human opens a terminal, runs `python run.py --serve`,
and copy-pastes the printed token into `options.html` before the extension does anything. The
extension should detect the bridge isn't running and start it itself.

## Why this doesn't relitigate the "never a daemon" decision

The epic's security section says the bridge "runs only under an explicit `python run.py --serve`;
never a daemon." That decision is about *what* the process is (a bridge holding Notion credentials
and filesystem access, not a background service that outlives the session), not about *who types
the command*. Chrome only ever starts a native-messaging host process in response to an explicit
extension call (`chrome.runtime.sendNativeMessage` / `connectNative`), which this story only fires
from an explicit human gesture — opening the side panel or a "Start bridge" click — never from an
extension background timer, never on browser/OS startup. So the invocation stays session-scoped
and human-triggered; only the keystrokes move from a terminal to the extension UI. Restate this
distinction in the native host's module docstring — it's the thing most likely to be
misread as "now it's a daemon."

**What genuinely changes:** today, a human reads a token off stdout and pastes it by hand — an
implicit visual confirmation that a *fresh* bridge process (this run's token) is the one paired to
the extension. After this story, `host.py` reads `config/extension_token.txt` and hands it to the
extension automatically, closing that human-in-the-loop pairing step. Mitigated by: the token file
is still regenerated fresh per `--serve` invocation (unchanged from `step-15a`), still git-ignored,
still loopback-only, and the manual paste flow in `options.html` remains available as a fallback —
this story doesn't remove it, it just stops requiring it on the happy path.

## Scope

**In:**
- A native-messaging host (`extension/native_host/host.py`) that, on an `ensure_started` request,
  checks `GET /health`, spawns `python run.py --serve --port <port>` detached if it isn't already
  up, polls `/health` until ready (bounded wait), and returns `{status, port, token}` — or a clear
  error if Python isn't on `PATH`, the repo can't be located, or the process didn't come up in
  time.
- The native messaging host manifest (`com.careerpilot.bridge_host.json`) and a Windows launcher
  wrapper (`run_host.bat`), since Chrome's native-messaging `path` must be a directly-executable
  file, not a bare `.py`.
- A one-time install script (`scripts/install_native_host.py`) that fills in absolute paths and
  registers the manifest — Windows registry (`HKCU\Software\Google\Chrome\NativeMessagingHosts\...`
  and the Edge equivalent) as the primary target for this repo's dev environment; POSIX manifest
  directory copy included for completeness, not separately verified here (no POSIX Chrome install
  available to test against in this environment — flagged in Verification below).
- `extension/background.js`: `ensureBridgeRunning()` — on a failed bridge call (`status: 0`,
  meaning the fetch itself couldn't connect, not an HTTP error), calls `sendNativeMessage`, stores
  the returned token/port in `chrome.storage.local`, and retries the original request once.
- `extension/panel.js` / `options.html`: replace the static "is `python run.py --serve` running?"
  text with a live status (checking → starting bridge → connected / manual-fallback-needed), and a
  link to the one-time native-host install step when native messaging itself isn't registered
  (`sendNativeMessage` fails with a distinct "host not found" error Chrome provides).

**Out:**
- Auto-starting on Chrome/OS boot, or any persistent/always-on service — explicitly the thing this
  story does not do (see "Why this doesn't relitigate" above).
- macOS support beyond the manifest file itself (no macOS environment to verify against here).
- Any change to `autoapply_server.py`'s routes or `build_application_plan()`/answer logic — this
  story only changes process lifecycle, not the bridge's request handling.

## Implementation

### `extension/native_host/host.py`

Chrome native-messaging wire protocol: each message on stdin/stdout is a 4-byte little-endian
length prefix followed by that many bytes of UTF-8 JSON. Read one message, act, write one response,
exit — Chrome relaunches the host process per `connectNative()` call, so this is not a long-lived
loop.

On `{"action": "ensure_started", "port": <int>}`:
1. `GET http://127.0.0.1:<port>/health` (short timeout). If `200`, respond
   `{"status": "already_running"}` — no spawn, no token re-read (an already-running bridge's token
   is presumably already what the extension holds).
2. Else, resolve the repo root as `Path(__file__).parents[2]` (this file lives at
   `extension/native_host/host.py`), and spawn
   `[sys.executable, "run.py", "--serve", "--port", str(port)]` with `cwd=repo_root`, detached
   (Windows: `creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP`;
   POSIX: `start_new_session=True`), stdout/stderr redirected away from the native host's own
   stdio (must not pollute the NM channel).
3. Poll `/health` every ~0.3s up to ~8s total.
4. On success, read `config/extension_token.txt` (same `TOKEN_PATH` `autoapply_server.py` writes)
   and respond `{"status": "started", "port": <int>, "token": "<str>"}`.
5. On timeout or any exception, respond `{"status": "error", "message": "<str>"}` — never raise
   past the wire-protocol write, since an unhandled exception here just looks like a hung host to
   Chrome, with no diagnostic surfaced anywhere the user can see it.

### `extension/native_host/com.careerpilot.bridge_host.json` + `run_host.bat`

Manifest fields: `name` (`com.careerpilot.bridge_host`), `description`, `path` (absolute, filled
in by the install script), `type: "stdio"`, `allowed_origins`
(`["chrome-extension://<EXTENSION_ID>/"]`). `run_host.bat` is a one-line wrapper
(`python "%~dp0host.py" %*`) since Chrome invokes `path` directly via `CreateProcess`, and a bare
`.py` has no reliable file association across machines.

### `scripts/install_native_host.py`

CLI: `python scripts/install_native_host.py --extension-id <id>` (the id is copied from
`chrome://extensions` after loading the unpacked extension once — this script cannot discover it,
since an unpacked extension's id is only assigned at load time absent a fixed `"key"` in
`manifest.json`, which this story does not add). Writes the manifest with resolved absolute paths
into `extension/native_host/`, then registers it:
- Windows: sets the default value of
  `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.careerpilot.bridge_host` (and the Edge
  hive) to the manifest's absolute path.
- POSIX: copies the manifest into the OS-specific native-messaging-hosts directory
  (`~/.config/google-chrome/NativeMessagingHosts/` on Linux,
  `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/` on macOS).

Idempotent — re-running with a new `--extension-id` (e.g. after a fresh unpacked load) overwrites
cleanly rather than erroring on an existing key/file.

### `extension/background.js`

Wrap the existing `bridgeFetch()`/`bridgeFetchBinary()`: on a result with `status: 0` (network
failure — the fetch never got an HTTP response, i.e. nothing is listening), call
`ensureBridgeRunning()` once before surfacing the failure:
```
chrome.runtime.sendNativeMessage(
  "com.careerpilot.bridge_host",
  { action: "ensure_started", port },
  (response) => { ... }
);
```
On `{status: "started"|"already_running", token}`, store `token`/`port` via
`chrome.storage.local.set` and retry the original request exactly once (never loop — a second
failure surfaces to the UI as today, not a retry storm). On `chrome.runtime.lastError` (host not
registered — the extension was never pointed at `install_native_host.py`'s output, or the id
mismatches), surface a distinct "native host not installed" state rather than the generic
"bridge unreachable" text, so the panel can point at the install step instead of telling the user
to open a terminal.

### `extension/panel.js` / `options.html`

Replace the two hardcoded "Bridge unreachable — is `python run.py --serve` running?" strings
(`panel.js:69,93`) with a small state machine: `checking → starting → connected` /
`native-host-missing` (link to install instructions) / `manual-fallback` (today's copy-paste flow,
kept as-is for anyone who didn't run the install script, or on a platform this story didn't wire
registration for).

## Reused verbatim

`GET /health` (`step-15a`) — the liveness check this story polls, unchanged. `TOKEN_PATH` /
`write_token()` / `read_token()` (`autoapply_server.py`, `step-15a`) — `host.py` reads the same
file the bridge already writes, no new token-generation logic. `run.py --serve --port` (`step-15a`)
— the exact command line this story now issues via `subprocess.Popen` instead of a human typing it.

## Files

**New:** `extension/native_host/host.py` · `extension/native_host/run_host.bat` ·
`extension/native_host/com.careerpilot.bridge_host.json` (template, paths filled at install time)
· `scripts/install_native_host.py` · `tests/test_native_host.py`.

**Modified:** `extension/manifest.json` (`"nativeMessaging"` permission) · `extension/background.js`
(`ensureBridgeRunning()`, wrapped `bridgeFetch`/`bridgeFetchBinary`) · `extension/panel.js` (status
state machine, replaces the two hardcoded unreachable strings) · `extension/options.html` /
`extension/options.js` (bridge-status indicator, install-step link, manual paste kept as fallback)
· `CLAUDE.md` (Stage 7 Layer 3 section, once this and the rest of Step 15 close out — tracked in
the epic's "Docs lifecycle", not duplicated here).

## Verification

Automated (`tests/test_native_host.py`, subprocess mocked — no real Chrome/process spawn in CI):
1. `ensure_started` against a mocked-healthy `/health` returns `already_running` and does not spawn
   a process.
2. `ensure_started` against a mocked-unreachable `/health` spawns exactly once with the expected
   command line and `cwd`, polls, and on a mocked-healthy poll returns `started` with the token read
   from a fixture token file.
3. A poll that never turns healthy within the bound returns `status: error` with a message, and
   does not hang past the timeout.
4. The wire-protocol read/write helpers round-trip a JSON payload through the 4-byte-length-prefix
   framing.
5. Any exception inside the spawn/poll path is caught and turned into a `status: error` response,
   never an unhandled exception (verifies point 5 of the Implementation section above).

**Live** (this repo's Windows dev environment; POSIX registration path is written but not
independently verified here — noted as a residual gap, not silently claimed done):
6. Fresh machine state (bridge not running, no token in `chrome.storage.local`): open the side
   panel → status shows checking → starting → connected, with no manual step, and a subsequent
   `/plan` call succeeds using the auto-populated token.
7. Bridge already running from a prior manual `--serve`: opening the panel shows connected
   immediately, with no duplicate process spawned (verify only one `python run.py --serve` process
   exists after).
8. Native host not installed (skip `install_native_host.py`): panel shows the
   native-host-missing state with a working link/instructions, and the manual copy-paste fallback
   in `options.html` still functions exactly as before this story.
9. Kill the bridge process out from under a connected extension, then trigger any bridge call: the
   extension re-detects, restarts, and recovers without a page reload.

## Risks

1. **Windows-only verified path.** POSIX manifest registration is written to the documented OS
   paths but not exercised against a real Chrome install in this environment — flag as a residual
   gap in this story's PR rather than claiming cross-platform parity.
2. **Silent token mismatch window.** Between an old bridge process being killed and a new one's
   `--serve` regenerating `config/extension_token.txt`, a very tight race could have `host.py` read
   a stale token file mid-write. Mitigated by `write_token()`'s existing single `Path.write_text()`
   call (atomic enough for this repo's threat model — a solo local dev tool, not a security
   boundary against a concurrent attacker) and by the bounded poll only returning `started` after
   `/health` itself confirms the *new* process is up.
3. **Chrome's native-messaging host lookup is finicky in practice** (exact `allowed_origins`
   match, manifest file permissions, registry hive mismatches between Chrome/Chromium/Edge builds).
   Expect the native-host-missing fallback path (Implementation, `panel.js`) to be exercised more
   than the happy path during initial rollout — this is why that state gets its own distinct UI
   message rather than collapsing into the generic "bridge unreachable" text.
4. **Maintenance** — same second-UI-surface-with-no-JS-test-runner risk the epic already names;
   `host.py` (Python) carries the real test coverage, `background.js`'s wiring stays thin and
   manually verified, consistent with every other sub-story.
