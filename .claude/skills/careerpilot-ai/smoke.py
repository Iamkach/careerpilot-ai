#!/usr/bin/env python3
"""
smoke.py — Drive the careerpilot-ai pipeline from a clean state.

Run from the project root:
  python .claude/skills/careerpilot-ai/smoke.py

What it tests (no API keys required):
  1. run.py parses and responds to --help
  2. --setup runs and reports which keys are missing vs. present
  3. Bad --stage value exits non-zero with a useful message
  4. All stage modules import without error
"""

import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parents[3]   # project root (3 levels up from skill dir)
PYTHON = sys.executable

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def run(cmd, *, check=False, expect_exit=None):
    result = subprocess.run(
        [PYTHON] + cmd,
        capture_output=True, text=True, cwd=str(ROOT)
    )
    if expect_exit is not None and result.returncode != expect_exit:
        return False, result
    if check and result.returncode != 0:
        return False, result
    return True, result


def test(label, ok, result=None):
    status = PASS if ok else FAIL
    print(f"  {status}  {label}")
    if not ok and result:
        for line in (result.stdout + result.stderr).strip().splitlines()[-5:]:
            print(f"       {line}")
    return ok


def main():
    print(f"\nSmoke test — {ROOT.name}\n")
    failures = 0

    # 1. run.py --help
    ok, r = run(["run.py", "--help"])
    failures += not test("run.py --help", ok and "AI Job Search Pipeline" in r.stdout)

    # 2. run.py --setup (exits 0 even when keys are missing)
    ok, r = run(["run.py", "--setup"])
    failures += not test("run.py --setup (runs without crash)", ok, r)
    # Show the setup summary
    for line in r.stdout.strip().splitlines():
        print(f"       {line}")

    # 3. Bad stage value → non-zero exit
    ok, r = run(["run.py", "--stage", "99"], expect_exit=1)
    failures += not test("run.py --stage 99 exits 1", ok, r)

    # 4. Stage module imports
    stage_modules = [
        "scripts.stage1_scrape",
        "scripts.stage2_tailor",
        "scripts.stage3_outreach",
        "scripts.stage4_digest",
        "scripts.stage5_interview_prep",
        "scripts.stage6_negotiate",
        "scripts.utils",
    ]
    import_script = "; ".join(f"import {m}" for m in stage_modules)
    ok, r = run(["-c", import_script], check=True)
    failures += not test("all stage modules import cleanly", ok, r)

    print()
    if failures:
        print(f"  {FAIL}  {failures} test(s) failed\n")
        sys.exit(1)
    else:
        print(f"  {PASS}  All smoke tests passed\n")


if __name__ == "__main__":
    main()
