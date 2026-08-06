#!/usr/bin/env python3
"""
install_native_host.py — one-time registration of step-15j's native-messaging host.

Spec: docs/backlog/step-15-application-prefill-extension.md, increment 8 (standalone native
launch).

Fills extension/native_host/com.careerpilot.bridge_host.json's placeholders (absolute path to
the host executable, the actual extension id) into a resolved, machine-specific manifest, then
registers that manifest with the browser:
  - Windows: sets the default value of
    HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.careerpilot.bridge_host (and the
    Edge hive) to the resolved manifest's absolute path.
  - POSIX: copies the resolved manifest into the OS-specific native-messaging-hosts directory
    (~/.config/google-chrome/NativeMessagingHosts/ on Linux, ~/Library/Application Support/
    Google/Chrome/NativeMessagingHosts/ on macOS) — written but not independently verified in
    this environment (no POSIX Chrome install available to test against here; flagged as a
    residual gap, not silently claimed done).

The extension id is not discoverable by this script: an unpacked extension's id is only
assigned at load time absent a fixed "key" in manifest.json, which this story does not add. Copy
it from chrome://extensions after loading the unpacked extension once:

    python scripts/install_native_host.py --extension-id <id from chrome://extensions>

Idempotent — re-running with a new --extension-id overwrites the resolved manifest and the
registry/copy target cleanly, no error on an existing key/file.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE_HOST_DIR = ROOT / "extension" / "native_host"
TEMPLATE_PATH = NATIVE_HOST_DIR / "com.careerpilot.bridge_host.json"
RESOLVED_PATH = NATIVE_HOST_DIR / "com.careerpilot.bridge_host.installed.json"
HOST_NAME = "com.careerpilot.bridge_host"

# HKCU-relative registry key paths whose default value must point at the resolved manifest.
_WINDOWS_HIVE_SUBPATHS = (
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
)


def _host_executable_path() -> Path:
    """The file Chrome actually invokes: run_host.bat on Windows (native-messaging `path` must
    be directly executable — a bare .py has no reliable file association across machines),
    host.py itself elsewhere."""
    if sys.platform == "win32":
        return NATIVE_HOST_DIR / "run_host.bat"
    return NATIVE_HOST_DIR / "host.py"


def build_manifest(extension_id: str) -> dict:
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    template["path"] = str(_host_executable_path().resolve())
    template["allowed_origins"] = [f"chrome-extension://{extension_id}/"]
    return template


def write_resolved_manifest(manifest: dict) -> Path:
    RESOLVED_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return RESOLVED_PATH


def register_windows(manifest_path: Path) -> list[str]:
    import winreg  # Windows-only stdlib module

    registered = []
    for hive_subpath in _WINDOWS_HIVE_SUBPATHS:
        key_path = f"{hive_subpath}\\{HOST_NAME}"
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
            winreg.CloseKey(key)
            registered.append(f"HKCU\\{key_path}")
        except OSError as e:
            print(f"  ! failed to register HKCU\\{key_path}: {e}")
    return registered


def register_posix(manifest_path: Path) -> list[str]:
    if sys.platform == "darwin":
        target_dir = (Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
                       / "NativeMessagingHosts")
    else:
        target_dir = Path.home() / ".config" / "google-chrome" / "NativeMessagingHosts"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{HOST_NAME}.json"
    shutil.copy(manifest_path, target)
    return [str(target)]


def install(extension_id: str) -> bool:
    manifest = build_manifest(extension_id)
    manifest_path = write_resolved_manifest(manifest)
    print(f"Wrote resolved manifest: {manifest_path}")

    registered = register_windows(manifest_path) if sys.platform == "win32" \
        else register_posix(manifest_path)

    if not registered:
        print("! Registration failed — see errors above.")
        return False

    print("Registered native messaging host at:")
    for r in registered:
        print(f"  {r}")
    if sys.platform not in ("win32", "darwin", "linux"):
        print(f"! Unrecognized platform {sys.platform!r} — registration path is unverified.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extension-id", required=True,
                         help="From chrome://extensions after loading the unpacked extension.")
    args = parser.parse_args()
    ok = install(args.extension_id)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
